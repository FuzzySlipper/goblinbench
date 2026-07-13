"""Codex app-server coding-agent runner.

Drives the locally managed Codex app-server over WebSocket-on-Unix-socket while
retaining GoblinBench's normal copied-fixture and filesystem-diff contract.
Unlike the bwrap CLI runner, the long-lived service cannot see a bwrap-only
mount namespace; the fixture's absolute host path is therefore the Codex cwd
and its only declared writable root.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import RunContext
from ..environment import snapshot_sha256
from ..fsutil import SKIP_DIRS_AGENT, compute_unified_diff, copy_directory, snapshot_directory
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso

MAX_INLINE_RAW_RESPONSE_CHARS = 32_768
DEFAULT_SOCKET_PATH = "/run/user/1001/codex-app-server/app-server.sock"
DEFAULT_TURN_START_ACK_TIMEOUT_SECONDS = 30.0
MAX_EVENT_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_BUFFERED_NOTIFICATIONS = 512
MAX_BUFFERED_NOTIFICATION_BYTES = 2 * 1024 * 1024
MAX_WEBSOCKET_FRAME_BYTES = 4 * 1024 * 1024


class NotificationBufferLimitExceeded(RuntimeError):
    """The server streamed too many notifications before an RPC response."""


class ProtocolFrameLimitExceeded(RuntimeError):
    """The server emitted a frame too large for a benchmark artifact."""


class EventCapture:
    """Stream bounded event evidence to disk instead of retaining it in gateway RAM."""

    def __init__(self, path: Path, max_bytes: int = MAX_EVENT_ARTIFACT_BYTES) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self.event_count = 0
        self.truncated = False
        self._handle: Any | None = None

    def __enter__(self) -> "EventCapture":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def record(self, event: dict[str, Any]) -> None:
        self.event_count += 1
        if self._handle is None or self.truncated:
            return
        encoded = (dumps(event) + "\n").encode("utf-8")
        if self.bytes_written + len(encoded) > self.max_bytes:
            marker = dumps({
                "direction": "runner",
                "event": "event artifact truncated",
                "max_bytes": self.max_bytes,
                "events_seen": self.event_count,
            }) + "\n"
            self._handle.write(marker)
            self._handle.flush()
            self.truncated = True
            return
        self._handle.write(encoded.decode("utf-8"))
        self._handle.flush()
        self.bytes_written += len(encoded)


class BoundedTextCapture:
    """Keep agent-visible text useful without retaining arbitrarily long deltas."""

    def __init__(self, max_chars: int = MAX_INLINE_RAW_RESPONSE_CHARS) -> None:
        self.max_chars = max_chars
        self.parts: list[str] = []
        self.length = 0
        self.truncated = False

    def append(self, value: str) -> None:
        remaining = self.max_chars - self.length
        if remaining <= 0:
            self.truncated = True
            return
        clipped = value[:remaining]
        self.parts.append(clipped)
        self.length += len(clipped)
        self.truncated = self.truncated or len(clipped) < len(value)

    def value(self) -> str:
        suffix = "\n...[truncated]" if self.truncated else ""
        return "".join(self.parts) + suffix


@dataclass(frozen=True)
class CodexAppServerConfig:
    socket_path: str
    task: str
    effort: str | None
    approval_policy: str
    network_access: bool
    model_provider: str | None
    turn_start_ack_timeout_seconds: float

    @classmethod
    def from_candidate(cls, candidate: CandidateConfig) -> "CodexAppServerConfig":
        cfg = candidate.config
        socket_path = str(cfg.get("socket_path") or DEFAULT_SOCKET_PATH)
        if not os.path.isabs(socket_path):
            raise ValueError("candidate.config.socket_path must be an absolute Unix socket path.")
        if not os.path.exists(socket_path):
            raise FileNotFoundError(f"Codex app-server socket not found: {socket_path}")
        effort = cfg.get("reasoning_effort") or cfg.get("effort")
        turn_start_ack_timeout_seconds = float(
            cfg.get("turn_start_ack_timeout_seconds", DEFAULT_TURN_START_ACK_TIMEOUT_SECONDS)
        )
        if turn_start_ack_timeout_seconds <= 0:
            raise ValueError("candidate.config.turn_start_ack_timeout_seconds must be positive.")
        return cls(
            socket_path=socket_path,
            task=str(cfg.get("task") or ""),
            effort=str(effort) if effort else None,
            approval_policy=str(cfg.get("approval_policy") or "never"),
            network_access=bool(cfg.get("network_access", False)),
            model_provider=str(cfg.get("model_provider")) if cfg.get("model_provider") else None,
            turn_start_ack_timeout_seconds=turn_start_ack_timeout_seconds,
        )


class CodexAppServerRunner:
    name = "codex-app-server"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return (
            candidate.kind is not None
            and candidate.kind.value == "CodingAgent"
            and str(candidate.config.get("runner") or "").strip().lower() == self.name
        )

    def run(
        self, scenario: Scenario, candidate: CandidateConfig, context: RunContext, timeout: float | None = None
    ) -> CandidateResult:
        started = time.perf_counter()
        trace: list[TraceEvent] = []
        artifact_dir = context.candidate_artifacts_directory(candidate.id)
        events = EventCapture(Path(artifact_dir) / "codex-events.jsonl")
        events.__enter__()

        def fail(error: str) -> CandidateResult:
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                success=False,
                error=error,
                duration_ms=int((time.perf_counter() - started) * 1000),
                trace=trace,
                artifact_directory=artifact_dir,
            )

        try:
            cfg = CodexAppServerConfig.from_candidate(candidate)
            task = cfg.task or _input_string(scenario, "task")
            if not task:
                return fail("No task prompt: provide scenario.input.task or candidate.config.task.")
            fixture_case = _input_string(scenario, "fixture_case")
            if not fixture_case:
                return fail("Scenario input missing 'fixture_case'.")
            repo_root = context.repo_root or _find_repo_root(context.runs_root)
            fixture_source = os.path.join(repo_root, "fixtures", "coding", fixture_case)
            if not os.path.isdir(fixture_source):
                return fail(f"Fixture directory not found: {fixture_source}")

            fixture_dest = os.path.join(context.candidate_directory(candidate.id), "fixture")
            copy_directory(fixture_source, fixture_dest, SKIP_DIRS_AGENT)
            before = snapshot_directory(fixture_dest, SKIP_DIRS_AGENT)
            workspace_hash = snapshot_sha256(before)
            trace.append(TraceEvent(now_iso(), "codex_app_server.fixture.copied", {
                "source": fixture_source, "destination": fixture_dest,
            }))

            assistant_text = BoundedTextCapture()
            timeout_seconds = float(timeout if timeout is not None else (scenario.timeout_seconds or 300))
            deadline = time.monotonic() + timeout_seconds
            thread_id = ""
            turn_id = ""
            turn_status = "failed"
            timed_out = False
            usage: dict[str, Any] = {}
            tool_item_ids: set[str] = set()
            command_item_ids: set[str] = set()
            server_version: str | None = None
            resolved_model = candidate.model
            resolved_provider = cfg.model_provider or "openai"

            with CodexAppServerClient(cfg.socket_path) as client:
                initialized = client.request("initialize", {
                    "clientInfo": {"name": "goblinbench", "version": "0.1"},
                }, deadline, events)
                server_version = _version_from_initialize(initialized)
                trace.append(TraceEvent(now_iso(), "codex_app_server.initialized", {
                    "socket_path": cfg.socket_path,
                    "server": initialized,
                }))
                client.notify("initialized", {})

                thread_params: dict[str, Any] = {
                    "cwd": os.path.abspath(fixture_dest),
                    "model": candidate.model,
                    "sandbox": "workspace-write",
                    "approvalPolicy": cfg.approval_policy,
                    "ephemeral": True,
                }
                if cfg.model_provider:
                    thread_params["modelProvider"] = cfg.model_provider
                thread_start_deadline = min(deadline, time.monotonic() + cfg.turn_start_ack_timeout_seconds)
                thread = client.request("thread/start", thread_params, thread_start_deadline, events)
                thread_dict = _as_dict(thread)
                resolved_model = str(thread_dict.get("model") or resolved_model or "unknown")
                resolved_provider = str(thread_dict.get("modelProvider") or resolved_provider)
                native_thread = _as_dict(thread_dict.get("thread"))
                server_version = str(native_thread.get("cliVersion") or server_version or "") or None
                thread_id = _result_id(thread, "thread")
                if not thread_id:
                    raise RuntimeError(f"Codex thread/start did not return a thread id: {thread}")

                turn_params: dict[str, Any] = {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": task}],
                    "sandboxPolicy": {
                        "type": "workspaceWrite",
                        "networkAccess": cfg.network_access,
                        "writableRoots": [os.path.abspath(fixture_dest)],
                    },
                }
                if cfg.effort:
                    turn_params["effort"] = cfg.effort
                turn_start_deadline = min(deadline, time.monotonic() + cfg.turn_start_ack_timeout_seconds)
                turn = client.request("turn/start", turn_params, turn_start_deadline, events)
                turn_id = _result_id(turn, "turn")
                if not turn_id:
                    raise RuntimeError(f"Codex turn/start did not return a turn id: {turn}")
                trace.append(TraceEvent(now_iso(), "codex_app_server.turn.started", {
                    "thread_id": thread_id, "turn_id": turn_id, "model": candidate.model,
                    "effort": cfg.effort, "fixture_dir": fixture_dest,
                }))

                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        try:
                            client.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, time.monotonic() + 10, events)
                        except Exception as exc:  # interrupt diagnostics only
                            events.record({"direction": "runner", "event": "turn/interrupt failed", "error": str(exc)})
                        turn_status = "interrupted"
                        break
                    try:
                        message = client.receive(remaining)
                    except TimeoutError:
                        timed_out = True
                        events.record({"direction": "runner", "event": "turn deadline exceeded"})
                        try:
                            client.request(
                                "turn/interrupt", {"threadId": thread_id, "turnId": turn_id},
                                time.monotonic() + 10, events,
                            )
                        except Exception as exc:  # preserve the partial run even if interrupt races shutdown
                            events.record({"direction": "runner", "event": "turn/interrupt failed", "error": str(exc)})
                        turn_status = "interrupted"
                        break
                    events.record({"direction": "server", "message": message})
                    if "id" in message and "method" in message:
                        client.respond_to_server_request(message, events)
                        continue
                    method = str(message.get("method") or "")
                    params = _as_dict(message.get("params"))
                    _collect_agent_text(method, params, assistant_text)
                    _collect_usage(method, params, usage)
                    _collect_activity(params, tool_item_ids, command_item_ids)
                    if method == "turn/completed":
                        completed_turn = _as_dict(params.get("turn")) or params
                        completed_id = _result_id(completed_turn, "turn")
                        if not completed_id or completed_id == turn_id:
                            turn_status = str(completed_turn.get("status") or "completed")
                            break

            after = snapshot_directory(fixture_dest, SKIP_DIRS_AGENT)
            diff = compute_unified_diff(before, after, fixture_dest)
            files_changed = diff.files_changed
            raw_response = assistant_text.value()
            _write_artifacts(artifact_dir, raw_response, diff.unified_diff_text)
            duration_ms = int((time.perf_counter() - started) * 1000)
            produced_changes = bool(files_changed)
            completed = turn_status == "completed" and not timed_out
            if timed_out:
                error = f"Codex turn timed out after {timeout_seconds:g}s."
            elif not completed:
                error = f"Codex turn completed with status {turn_status!r}."
            elif not produced_changes:
                error = "Codex turn completed but produced no fixture file changes."
            else:
                error = None
            trace.append(TraceEvent(now_iso(), "codex_app_server.completed", {
                "thread_id": thread_id, "turn_id": turn_id, "turn_status": turn_status,
                "timed_out": timed_out, "files_changed": len(files_changed), "duration_ms": duration_ms,
            }))
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=ModelIdentity(
                    model=resolved_model,
                    provider=resolved_provider,
                    base_url=f"unix://{cfg.socket_path}",
                    display_name=f"codex-app-server:{candidate.model}",
                ),
                success=completed and produced_changes,
                error=error,
                duration_ms=duration_ms,
                raw_response=_truncate(raw_response),
                output={
                    "fixture_dir": fixture_dest,
                    "fixture_case": fixture_case,
                    "patch": diff.unified_diff_text,
                    "files_changed": files_changed,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "turn_status": turn_status,
                    "socket_path": cfg.socket_path,
                    "transport": "websocket-over-unix",
                    "requested_model": candidate.model,
                    "reasoning_effort": cfg.effort,
                    "timed_out": timed_out,
                },
                trace=trace,
                artifact_directory=artifact_dir,
                environment={
                    "lane": "environment-realized",
                    "name": "codex-app-server-direct",
                    "model": {
                        "requested": candidate.model,
                        "resolved": resolved_model,
                        "provider_requested": candidate.provider,
                        "provider_resolved": resolved_provider,
                        "reasoning_effort": cfg.effort,
                    },
                    "substrate": {
                        "kind": "codex-app-server",
                        "name": "codex-app-server-direct",
                        "version": server_version,
                        "transport": "websocket-over-unix",
                        "socket_path": cfg.socket_path,
                    },
                    "harness": {"workspace_sha256": workspace_hash},
                    "execution": {
                        "runner_status": "completed" if completed and produced_changes else "failed",
                        "substrate_status": turn_status,
                        "terminal_status": turn_status,
                        "retries": 0,
                        "tool_calls": len(tool_item_ids),
                        "command_cycles": len(command_item_ids),
                    },
                    "usage": _normalized_usage(usage),
                    "identifiers": {"native_thread_id": thread_id, "native_turn_id": turn_id},
                },
            )
        except Exception as exc:  # runner boundary: preserve a bounded, non-secret failure artifact
            events.record({"direction": "runner", "event": "runner failure", "error": str(exc)})
            return fail(f"CodexAppServerRunner failed: {exc}")
        finally:
            events.close()


class CodexAppServerClient:
    """Minimal RFC 6455 text-frame client for Codex's Unix-socket transport."""

    def __init__(
        self,
        socket_path: str,
        *,
        max_notifications: int = MAX_BUFFERED_NOTIFICATIONS,
        max_notification_bytes: int = MAX_BUFFERED_NOTIFICATION_BYTES,
        max_frame_bytes: int = MAX_WEBSOCKET_FRAME_BYTES,
    ) -> None:
        self.socket_path = socket_path
        self.max_notifications = max_notifications
        self.max_notification_bytes = max_notification_bytes
        self.max_frame_bytes = max_frame_bytes
        self.sock: socket.socket | None = None
        self.next_id = 1
        self.pending: dict[int, dict[str, Any]] = {}
        self.notifications: list[tuple[dict[str, Any], int]] = []
        self.notification_bytes = 0
        self._buffer = b""

    def __enter__(self) -> "CodexAppServerClient":
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(15)
        self.sock.connect(self.socket_path)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        header = self._read_http_header()
        first_line = header.split(b"\r\n", 1)[0].decode("ascii", "replace")
        if " 101 " not in first_line:
            raise RuntimeError(f"Codex app-server WebSocket upgrade failed: {first_line}")
        self.sock.settimeout(None)
        return self

    def __exit__(self, *_: Any) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        if self.sock:
            self.sock.close()
            self.sock = None

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send_json({"method": method, "params": params})

    def request(self, method: str, params: dict[str, Any], deadline: float, events: EventCapture) -> Any:
        request_id = self.next_id
        self.next_id += 1
        self._send_json({"id": request_id, "method": method, "params": params})
        while True:
            # Do not call receive() here: it drains and requeues preserved notifications,
            # which can replay one server event forever while an RPC response is pending.
            message = self._receive_from_socket(max(0.01, deadline - time.monotonic()))
            events.record({"direction": "server", "message": message})
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise RuntimeError(f"Codex {method} failed: {message['error']}")
                return message.get("result")
            if "id" in message and "method" in message:
                self.respond_to_server_request(message, events)
            else:
                self._buffer_notification(message)

    def receive(self, timeout: float) -> dict[str, Any]:
        if self.notifications:
            message, byte_count = self.notifications.pop(0)
            self.notification_bytes -= byte_count
            return message
        return self._receive_from_socket(timeout)

    def _receive_from_socket(self, timeout: float) -> dict[str, Any]:
        if timeout <= 0:
            raise TimeoutError("Codex app-server event deadline exceeded")
        assert self.sock is not None
        self.sock.settimeout(timeout)
        try:
            while True:
                opcode, payload = self._read_frame()
                if opcode == 0x9:
                    self._send_frame(0xA, payload)
                    continue
                if opcode == 0x8:
                    raise ConnectionError("Codex app-server closed the WebSocket")
                if opcode != 0x1:
                    continue
                value = json.loads(payload.decode("utf-8"))
                if not isinstance(value, dict):
                    continue
                return value
        finally:
            self.sock.settimeout(None)

    def _buffer_notification(self, message: dict[str, Any]) -> None:
        byte_count = len(dumps(message).encode("utf-8"))
        if byte_count > self.max_notification_bytes:
            raise NotificationBufferLimitExceeded(
                f"Codex notification is {byte_count} bytes; limit is {self.max_notification_bytes} bytes."
            )
        if (
            len(self.notifications) >= self.max_notifications
            or self.notification_bytes + byte_count > self.max_notification_bytes
        ):
            raise NotificationBufferLimitExceeded(
                "Codex notification backlog exceeded bounded runner capacity "
                f"({len(self.notifications)} events, {self.notification_bytes} bytes)."
            )
        self.notifications.append((message, byte_count))
        self.notification_bytes += byte_count

    def respond_to_server_request(self, message: dict[str, Any], events: EventCapture) -> None:
        method = str(message.get("method") or "")
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return
        if method.endswith("requestApproval"):
            result: dict[str, Any] = {"decision": "decline"}
        elif method.endswith("requestUserInput"):
            result = {"answers": {}}
        else:
            result = {"permissions": {}}
        events.record({"direction": "runner", "reply_to": method, "id": request_id, "result": result})
        self._send_json({"id": request_id, "result": result})

    def _read_http_header(self) -> bytes:
        assert self.sock is not None
        while b"\r\n\r\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Codex app-server closed during WebSocket upgrade")
            self._buffer += chunk
        header, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        return header

    def _send_json(self, payload: dict[str, Any]) -> None:
        self._send_frame(0x1, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        assert self.sock is not None
        mask = secrets.token_bytes(4)
        length = len(payload)
        if length < 126:
            header = bytes([0x80 | opcode, 0x80 | length])
        elif length < 65536:
            header = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack("!Q", length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _read_frame(self) -> tuple[int, bytes]:
        first, second = self._read_exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        if length > self.max_frame_bytes:
            raise ProtocolFrameLimitExceeded(
                f"Codex WebSocket frame is {length} bytes; limit is {self.max_frame_bytes} bytes."
            )
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length)
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return opcode, payload

    def _read_exact(self, length: int) -> bytes:
        assert self.sock is not None
        while len(self._buffer) < length:
            chunk = self.sock.recv(max(4096, length - len(self._buffer)))
            if not chunk:
                raise ConnectionError("Codex app-server closed the WebSocket")
            self._buffer += chunk
        value, self._buffer = self._buffer[:length], self._buffer[length:]
        return value


def _collect_agent_text(method: str, params: dict[str, Any], text: BoundedTextCapture) -> None:
    if method == "item/agentMessage/delta":
        delta = params.get("delta")
        if isinstance(delta, str):
            text.append(delta)
    elif method == "item/completed":
        item = _as_dict(params.get("item")) or params
        if str(item.get("type") or "") == "agentMessage":
            value = item.get("text") or item.get("content")
            if isinstance(value, str) and value and not text.parts:
                text.append(value)


def _collect_usage(method: str, params: dict[str, Any], target: dict[str, Any]) -> None:
    if method != "thread/tokenUsage/updated":
        return
    token_usage = _as_dict(params.get("tokenUsage"))
    total = _as_dict(token_usage.get("total"))
    if total:
        target.clear()
        target.update(total)
        target["modelContextWindow"] = token_usage.get("modelContextWindow")


def _collect_activity(
    params: dict[str, Any], tool_item_ids: set[str], command_item_ids: set[str]
) -> None:
    item = _as_dict(params.get("item"))
    item_id = item.get("id")
    item_type = str(item.get("type") or "")
    if not isinstance(item_id, str) or not item_id:
        return
    if item_type == "commandExecution":
        command_item_ids.add(item_id)
    elif item_type in {"dynamicToolCall", "mcpToolCall", "webSearch", "imageView", "collabToolCall"}:
        tool_item_ids.add(item_id)


def _normalized_usage(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_tokens": value.get("inputTokens"),
        "cached_input_tokens": value.get("cachedInputTokens"),
        "output_tokens": value.get("outputTokens"),
        "reasoning_output_tokens": value.get("reasoningOutputTokens"),
        "total_tokens": value.get("totalTokens"),
        "model_context_window": value.get("modelContextWindow"),
    }


def _version_from_initialize(value: Any) -> str | None:
    initialized = _as_dict(value)
    server = _as_dict(initialized.get("serverInfo"))
    version = server.get("version") or initialized.get("version")
    if isinstance(version, str) and version:
        return version
    user_agent = initialized.get("userAgent")
    if isinstance(user_agent, str) and "/" in user_agent:
        candidate = user_agent.split("/", 1)[1].split(" ", 1)[0]
        return candidate or None
    return None


def _result_id(value: Any, kind: str) -> str:
    if not isinstance(value, dict):
        return ""
    nested = value.get(kind)
    if isinstance(nested, dict):
        value = nested
    for key in ("id", f"{kind}Id", f"{kind}_id"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _input_string(scenario: Scenario, key: str) -> str:
    value = scenario.input.get(key)
    return value if isinstance(value, str) else ""


def _find_repo_root(runs_root: str) -> str:
    current = Path(runs_root).resolve()
    for parent in (current, *current.parents):
        if (parent / "fixtures" / "coding").is_dir():
            return str(parent)
    raise FileNotFoundError("Could not determine GoblinBench repo root from runs_root.")


def _truncate(value: str) -> str:
    if len(value) <= MAX_INLINE_RAW_RESPONSE_CHARS:
        return value
    return value[:MAX_INLINE_RAW_RESPONSE_CHARS] + "\n...[truncated]"


def _write_artifacts(artifact_dir: str, response: str, patch: str) -> None:
    os.makedirs(artifact_dir, exist_ok=True)
    Path(os.path.join(artifact_dir, "codex-response.txt")).write_text(response, encoding="utf-8")
    Path(os.path.join(artifact_dir, "agent.patch")).write_text(patch, encoding="utf-8")
