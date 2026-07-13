"""Rusty Crew external-agent coding runner.

Uses only Rusty Crew's supported HTTP session/message/event surfaces. It never
reads Crew databases or imports Crew internals. Live use is debug-service-only
by default so benchmark sessions cannot contaminate the production Crew store.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import RunContext
from ..environment import json_sha256, snapshot_sha256
from ..fsutil import SKIP_DIRS_AGENT, compute_unified_diff, copy_directory, snapshot_directory
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso

DEFAULT_DEBUG_BASE_URL = "http://127.0.0.1:9348"
DEFAULT_DEBUG_SERVICE_UNIT = "rusty-crew-debug.service"
MAX_EVENT_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_CHARS = 32_768


class RustyCrewApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class RustyCrewConfig:
    base_url: str
    runtime_id: str
    profile_id: str
    task: str
    effort: str | None
    service_unit: str
    require_debug_service: bool
    auth_token_env: str | None
    poll_interval_seconds: float

    @classmethod
    def from_candidate(cls, candidate: CandidateConfig) -> "RustyCrewConfig":
        cfg = candidate.config
        base_url = str(cfg.get("base_url") or candidate.base_url or DEFAULT_DEBUG_BASE_URL).rstrip("/")
        runtime_id = str(cfg.get("runtime_id") or "").strip()
        profile_id = str(cfg.get("profile_id") or candidate.profile or "").strip()
        if not runtime_id:
            raise ValueError("candidate.config.runtime_id is required for rusty-crew runner")
        if not profile_id:
            raise ValueError("candidate.config.profile_id is required for rusty-crew runner")
        require_debug = bool(cfg.get("require_debug_service", True))
        if require_debug and not _is_debug_url(base_url):
            raise ValueError(
                f"rusty-crew runner refuses non-debug endpoint {base_url!r}; "
                "use the rusty-crew-debug.service endpoint on 127.0.0.1:9348"
            )
        poll_interval = float(cfg.get("poll_interval_seconds", 0.25))
        if poll_interval <= 0:
            raise ValueError("candidate.config.poll_interval_seconds must be positive")
        effort = cfg.get("reasoning_effort") or cfg.get("effort")
        return cls(
            base_url=base_url,
            runtime_id=runtime_id,
            profile_id=profile_id,
            task=str(cfg.get("task") or ""),
            effort=str(effort) if effort else None,
            service_unit=str(cfg.get("service_unit") or DEFAULT_DEBUG_SERVICE_UNIT),
            require_debug_service=require_debug,
            auth_token_env=str(cfg.get("auth_token_env")) if cfg.get("auth_token_env") else None,
            poll_interval_seconds=poll_interval,
        )


class RustyCrewClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get(self, path: str, timeout: float) -> Any:
        return self._request("GET", path, None, timeout)

    def post(self, path: str, body: dict[str, Any], timeout: float) -> Any:
        return self._request("POST", path, body, timeout)

    def _request(self, method: str, path: str, body: dict[str, Any] | None, timeout: float) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=max(0.1, timeout)) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = response.getcode()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RustyCrewApiError(f"Rusty Crew HTTP {exc.code} {path}: {_error_message(raw)}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RustyCrewApiError(f"Rusty Crew request failed {method} {path}: {exc}") from exc
        if not 200 <= status < 300:
            raise RustyCrewApiError(f"Rusty Crew HTTP {status} {path}: {_error_message(raw)}")
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RustyCrewApiError(f"Rusty Crew returned non-JSON for {path}") from exc
        if not isinstance(envelope, dict) or envelope.get("ok") is not True:
            raise RustyCrewApiError(f"Rusty Crew error for {path}: {_error_message(raw)}")
        return envelope.get("data")


class RustyCrewRunner:
    name = "rusty-crew"

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
        artifact_dir = Path(context.candidate_artifacts_directory(candidate.id))
        artifact_dir.mkdir(parents=True, exist_ok=True)

        def fail(error: str, environment: dict[str, Any] | None = None) -> CandidateResult:
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                success=False,
                error=error,
                duration_ms=int((time.perf_counter() - started) * 1000),
                trace=trace,
                artifact_directory=str(artifact_dir),
                environment=environment or {"lane": "environment-realized", "name": "rusty-crew-debug"},
            )

        try:
            cfg = RustyCrewConfig.from_candidate(candidate)
            if cfg.require_debug_service:
                _verify_debug_service(cfg.service_unit)
            task = cfg.task or _input_string(scenario, "task")
            fixture_case = _input_string(scenario, "fixture_case")
            if not task:
                return fail("No task prompt: provide scenario.input.task or candidate.config.task.")
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
            trace.append(TraceEvent(now_iso(), "rusty_crew.fixture.copied", {
                "source": fixture_source, "destination": fixture_dest, "workspace_sha256": workspace_hash,
            }))

            timeout_seconds = float(timeout if timeout is not None else (scenario.timeout_seconds or 300))
            deadline = time.monotonic() + timeout_seconds
            token = os.environ.get(cfg.auth_token_env) if cfg.auth_token_env else None
            client = RustyCrewClient(cfg.base_url, token)

            fleet = client.get("/v1/external-runtimes", _remaining(deadline))
            runtime = _find_runtime(fleet, cfg.runtime_id)
            controller = _find_controller(fleet, cfg.runtime_id)
            if runtime.get("observedState") != "ready" or controller.get("driverState") != "ready":
                raise RustyCrewApiError(
                    f"Rusty Crew runtime {cfg.runtime_id!r} is not ready: "
                    f"runtime={runtime.get('observedState')!r}, controller={controller.get('driverState')!r}"
                )

            profile_page = client.get("/v1/admin/profiles/registry?limit=100", _remaining(deadline))
            profile = _find_profile(profile_page, cfg.profile_id)
            if profile.get("lifecycleStatus") != "active":
                raise RustyCrewApiError(f"Rusty Crew profile {cfg.profile_id!r} is not active")
            tool_identity = {
                "localToolProfileId": profile.get("localToolProfileId"),
                "toolPolicy": profile.get("toolPolicy"),
                "mcpBindings": profile.get("mcpBindings"),
            }
            tool_hash = json_sha256(tool_identity)
            cursor = _latest_event_cursor(client, cfg.runtime_id, deadline)

            identity = _id_prefix(context.run_id, scenario.id, candidate.id)
            creation = client.post("/v1/external-agent-sessions", {
                "idempotencyKey": f"{identity}:create",
                "runtimeId": cfg.runtime_id,
                "profileId": cfg.profile_id,
                "cwd": os.path.abspath(fixture_dest),
                "label": f"GoblinBench {scenario.id} / {candidate.id}",
            }, _remaining(deadline))
            creation_state = _dict(creation.get("creation"))
            if creation_state.get("phase") != "ready":
                raise RustyCrewApiError(f"external agent session did not become ready: {creation_state}")
            binding = _dict(creation_state.get("binding"))
            session = _dict(creation_state.get("session"))
            binding_id = _required_string(binding, "bindingId")
            session_id = _required_string(session, "sessionId")
            native_thread_id = _required_string(creation_state, "nativeThreadId")

            catalog_path = f"/v1/external-bindings/{_quote(binding_id)}/commands"
            catalog = client.get(catalog_path, _remaining(deadline))
            command_count = 0
            resolved_model = _dict(catalog.get("settings")).get("model")
            if candidate.model:
                model_option = _find_model_option(catalog, candidate.model)
                if resolved_model != model_option.get("model"):
                    _apply_command(client, catalog_path, f"/model {_required_string(model_option, 'id')}",
                                   f"{identity}:model", deadline)
                    command_count += 1
                resolved_model = model_option.get("model")
            if cfg.effort:
                model_option = _find_model_option(catalog, str(resolved_model))
                efforts = [_dict(value).get("value") for value in model_option.get("supportedEfforts") or []]
                if cfg.effort not in efforts:
                    raise RustyCrewApiError(
                        f"effort {cfg.effort!r} is not advertised for model {resolved_model!r}: {efforts}"
                    )
                _apply_command(client, catalog_path, f"/effort {cfg.effort}", f"{identity}:effort", deadline)
                command_count += 1
            catalog = client.get(catalog_path, _remaining(deadline))
            settings = _dict(catalog.get("settings"))
            resolved_model = str(settings.get("model") or resolved_model or candidate.model or "unknown")
            resolved_provider = str(settings.get("modelProvider") or "openai")
            resolved_effort = settings.get("effort")

            delivery = client.post(f"/v1/external-bindings/{_quote(binding_id)}/messages", {
                "deliveryId": f"{identity}:delivery",
                "idempotencyKey": f"{identity}:delivery",
                "messageId": f"{identity}:message",
                "body": task,
                "ttlMs": 60_000,
            }, _remaining(deadline))
            activation = _dict(delivery.get("activation"))
            if activation.get("type") != "external_turn_requested":
                raise RustyCrewApiError(f"message did not request an external turn: {activation}")
            request_id = _required_string(activation, "requestId")
            turn = _wait_for_turn(client, request_id, deadline, cfg.poll_interval_seconds)
            native_turn_id = str(turn.get("nativeTurnId") or "")
            events = _wait_for_turn_events(
                client, cfg.runtime_id, cursor, native_thread_id, native_turn_id,
                deadline, cfg.poll_interval_seconds,
            )
            _write_jsonl_bounded(artifact_dir / "rusty-crew-events.jsonl", events)
            assistant_text = _assistant_text(events)
            (artifact_dir / "rusty-crew-response.txt").write_text(assistant_text, encoding="utf-8")

            after = snapshot_directory(fixture_dest, SKIP_DIRS_AGENT)
            diff = compute_unified_diff(before, after, fixture_dest)
            (artifact_dir / "agent.patch").write_text(diff.unified_diff_text, encoding="utf-8")
            duration_ms = int((time.perf_counter() - started) * 1000)
            terminal_phase = str(turn.get("phase") or "unknown")
            completed = terminal_phase == "completed"
            produced_changes = bool(diff.files_changed)
            usage = _usage(events)
            tool_calls, command_cycles = _activity_counts(events)

            if not completed:
                error = f"Rusty Crew external turn completed with phase {terminal_phase!r}."
            elif not produced_changes:
                error = "Rusty Crew external turn completed but produced no fixture file changes."
            else:
                error = None
            environment = {
                "lane": "environment-realized",
                "name": "rusty-crew-debug",
                "model": {
                    "requested": candidate.model,
                    "resolved": resolved_model,
                    "provider_requested": candidate.provider,
                    "provider_resolved": resolved_provider,
                    "reasoning_effort": resolved_effort,
                },
                "substrate": {
                    "kind": "rusty-crew-external-agent",
                    "name": cfg.service_unit,
                    "version": None,
                    "transport": "http-to-websocket-over-unix",
                    "base_url": cfg.base_url,
                    "runtime_id": cfg.runtime_id,
                    "runtime_revision": runtime.get("revision"),
                    "app_server_version": runtime.get("expectedCliVersion"),
                    "app_server_executable_sha256": runtime.get("executableSha256"),
                    "protocol_schema_sha256": runtime.get("protocolSchemaSha256"),
                },
                "profile": {
                    "id": cfg.profile_id,
                    "revision": profile.get("revision"),
                    "role": profile.get("displayName"),
                    "prompt_assembly_id": profile.get("providerAlias"),
                    "tool_catalog_sha256": tool_hash,
                    "local_tool_profile_id": profile.get("localToolProfileId"),
                },
                "harness": {"workspace_sha256": workspace_hash},
                "execution": {
                    "runner_status": "completed" if completed and produced_changes else "failed",
                    "substrate_status": terminal_phase,
                    "terminal_status": terminal_phase,
                    "retries": 0,
                    "tool_calls": tool_calls,
                    "command_cycles": command_cycles,
                    "configuration_commands": command_count,
                },
                "usage": usage,
                "cost": {
                    "classification": "opaque-subscription",
                    "amount": None,
                    "currency": None,
                    "basis": "Codex subscription through Rusty Crew; no per-run charge exposed",
                },
                "identifiers": {
                    "session_id": session_id,
                    "binding_id": binding_id,
                    "native_thread_id": native_thread_id,
                    "native_turn_id": native_turn_id or None,
                    "external_turn_request_id": request_id,
                },
            }
            trace.append(TraceEvent(now_iso(), "rusty_crew.completed", {
                "session_id": session_id, "binding_id": binding_id,
                "native_thread_id": native_thread_id, "native_turn_id": native_turn_id,
                "phase": terminal_phase, "files_changed": len(diff.files_changed),
                "duration_ms": duration_ms,
            }))
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=ModelIdentity(
                    model=resolved_model,
                    provider=resolved_provider,
                    base_url=cfg.base_url,
                    display_name=f"rusty-crew:{cfg.profile_id}:{resolved_model}",
                ),
                success=completed and produced_changes,
                error=error,
                duration_ms=duration_ms,
                raw_response=assistant_text[:MAX_RESPONSE_CHARS],
                output={
                    "fixture_dir": fixture_dest,
                    "fixture_case": fixture_case,
                    "patch": diff.unified_diff_text,
                    "files_changed": diff.files_changed,
                    "runtime_id": cfg.runtime_id,
                    "profile_id": cfg.profile_id,
                    "session_id": session_id,
                    "binding_id": binding_id,
                    "thread_id": native_thread_id,
                    "turn_id": native_turn_id,
                    "turn_status": terminal_phase,
                    "requested_model": candidate.model,
                    "resolved_model": resolved_model,
                    "reasoning_effort": resolved_effort,
                    "timed_out": False,
                },
                trace=trace,
                artifact_directory=str(artifact_dir),
                environment=environment,
            )
        except Exception as exc:  # noqa: BLE001
            return fail(f"RustyCrewRunner failed: {exc}")


def _verify_debug_service(service_unit: str) -> None:
    if service_unit != DEFAULT_DEBUG_SERVICE_UNIT:
        raise ValueError(f"debug-safe runner requires service_unit={DEFAULT_DEBUG_SERVICE_UNIT!r}")
    result = subprocess.run(
        ["systemctl", "--user", "is-active", service_unit],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0 or result.stdout.strip() != "active":
        raise RuntimeError(f"{service_unit} is not active")


def _is_debug_url(base_url: str) -> bool:
    parsed = urllib.parse.urlparse(base_url)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 9348


def _find_runtime(fleet: Any, runtime_id: str) -> dict[str, Any]:
    for runtime in _dict(fleet).get("runtimes") or []:
        if _dict(runtime).get("runtimeId") == runtime_id:
            return _dict(runtime)
    raise RustyCrewApiError(f"Rusty Crew runtime not found: {runtime_id}")


def _find_controller(fleet: Any, runtime_id: str) -> dict[str, Any]:
    for controller in _dict(fleet).get("controllers") or []:
        if _dict(controller).get("runtimeId") == runtime_id:
            return _dict(controller)
    raise RustyCrewApiError(f"Rusty Crew controller not found: {runtime_id}")


def _find_profile(page: Any, profile_id: str) -> dict[str, Any]:
    for profile in _dict(page).get("items") or []:
        if _dict(profile).get("profileId") == profile_id:
            return _dict(profile)
    raise RustyCrewApiError(f"Rusty Crew profile not found: {profile_id}")


def _find_model_option(catalog: Any, requested: str) -> dict[str, Any]:
    for option in _dict(catalog).get("models") or []:
        value = _dict(option)
        if requested in {value.get("id"), value.get("model")}:
            return value
    raise RustyCrewApiError(f"Rusty Crew model catalog does not advertise {requested!r}")


def _apply_command(
    client: RustyCrewClient, path: str, command: str, idempotency_key: str, deadline: float
) -> dict[str, Any]:
    result = _dict(client.post(path, {"input": command, "idempotencyKey": idempotency_key}, _remaining(deadline)))
    if result.get("status") != "applied":
        raise RustyCrewApiError(
            f"Rusty Crew command {command!r} was not applied: {result.get('reasonCode') or result.get('message')}"
        )
    return result


def _latest_event_cursor(client: RustyCrewClient, runtime_id: str, deadline: float) -> int:
    cursor = 0
    while True:
        page = _dict(client.get(
            f"/v1/external-runtimes/{_quote(runtime_id)}/events?after={cursor}&limit=1000",
            _remaining(deadline),
        ))
        events = page.get("events") or []
        if not events:
            return cursor
        cursor = int(_dict(events[-1]).get("sequenceId") or cursor)
        if len(events) < 1000:
            return cursor


def _wait_for_turn(
    client: RustyCrewClient, request_id: str, deadline: float, poll_interval: float
) -> dict[str, Any]:
    terminal = {"completed", "failed", "interrupted", "outcome_unknown", "expired"}
    while time.monotonic() < deadline:
        turn = _dict(client.get(f"/v1/external-turns/{_quote(request_id)}", _remaining(deadline)))
        if turn.get("phase") in terminal:
            return turn
        time.sleep(min(poll_interval, max(0.01, _remaining(deadline))))
    raise TimeoutError("timed out waiting for Rusty Crew external turn")


def _wait_for_turn_events(
    client: RustyCrewClient,
    runtime_id: str,
    cursor: int,
    thread_id: str,
    turn_id: str,
    deadline: float,
    poll_interval: float,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        page = _dict(client.get(
            f"/v1/external-runtimes/{_quote(runtime_id)}/events?after={cursor}&limit=1000",
            _remaining(deadline),
        ))
        fresh = [_dict(event) for event in page.get("events") or []]
        if fresh:
            cursor = int(fresh[-1].get("sequenceId") or cursor)
            events.extend(event for event in fresh if event.get("nativeThreadId") == thread_id)
        if any(
            event.get("nativeTurnId") == turn_id
            and _dict(event.get("payload")).get("nativeMethod") in {"turn/completed", "turn/interrupted"}
            for event in events
        ):
            return events
        time.sleep(min(poll_interval, max(0.01, _remaining(deadline))))
    return events  # terminal turn row is authoritative; retain partial replay evidence


def _assistant_text(events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for event in events:
        if event.get("kind") != "assistant_text_delta":
            continue
        text = _dict(event.get("payload")).get("text")
        if isinstance(text, str):
            parts.append(text)
    value = "".join(parts)
    return value[:MAX_RESPONSE_CHARS] + ("\n...[truncated]" if len(value) > MAX_RESPONSE_CHARS else "")


def _usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    total: dict[str, Any] = {}
    context_window = None
    for event in events:
        usage = _dict(_dict(event.get("payload")).get("usage"))
        if usage:
            total = _dict(usage.get("total"))
            context_window = usage.get("modelContextWindow")
    return {
        "input_tokens": total.get("inputTokens"),
        "cached_input_tokens": total.get("cachedInputTokens"),
        "output_tokens": total.get("outputTokens"),
        "reasoning_output_tokens": total.get("reasoningOutputTokens"),
        "total_tokens": total.get("totalTokens"),
        "model_context_window": context_window,
    }


def _activity_counts(events: list[dict[str, Any]]) -> tuple[int, int]:
    tool_ids = {
        event.get("itemId") for event in events
        if event.get("itemId") and event.get("kind") in {"tool_activity", "tool_call", "tool_result", "server_request"}
    }
    command_ids = {
        event.get("itemId") for event in events
        if event.get("itemId")
        and event.get("kind") in {"command_activity", "file_activity", "command_execution", "file_change"}
    }
    return len(tool_ids), len(command_ids)


def _write_jsonl_bounded(path: Path, events: list[dict[str, Any]]) -> None:
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            line = dumps(event, indent=None) + "\n"
            size = len(line.encode("utf-8"))
            if written + size > MAX_EVENT_ARTIFACT_BYTES:
                handle.write(dumps({"event": "truncated", "max_bytes": MAX_EVENT_ARTIFACT_BYTES}, indent=None) + "\n")
                break
            handle.write(line)
            written += size


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Rusty Crew benchmark deadline exceeded")
    return remaining


def _input_string(scenario: Scenario, key: str) -> str:
    value = scenario.input.get(key)
    return value if isinstance(value, str) else ""


def _id_prefix(run_id: str, scenario_id: str, candidate_id: str) -> str:
    raw = f"goblinbench:{run_id}:{scenario_id}:{candidate_id}"
    return raw[:220]


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise RustyCrewApiError(f"Rusty Crew response missing {key}: {value}")
    return result


def _error_message(raw: str) -> str:
    try:
        value = json.loads(raw)
        error = _dict(value).get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("reason_code") or error)[:500]
    except json.JSONDecodeError:
        pass
    return raw[:500]


def _find_repo_root(runs_root: str) -> str:
    return os.path.dirname(os.path.abspath(runs_root))
