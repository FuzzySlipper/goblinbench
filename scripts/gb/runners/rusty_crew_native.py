"""Rusty Crew native-brain coding runner.

Creates one disposable profile/session through the supported control API, sends
one turn through the public chat API, captures durable events and bounded debug
details, then deletes the profile. Live use is debug-service-only by default.
"""

from __future__ import annotations

import os
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import RunContext
from ..environment import json_sha256, snapshot_sha256
from ..fsutil import SKIP_DIRS_AGENT, compute_unified_diff, copy_directory, snapshot_directory
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso
from .rusty_crew import (
    DEFAULT_DEBUG_BASE_URL,
    DEFAULT_DEBUG_SERVICE_UNIT,
    MAX_EVENT_ARTIFACT_BYTES,
    MAX_RESPONSE_CHARS,
    RustyCrewApiError,
    RustyCrewClient,
    _dict,
    _find_repo_root,
    _input_string,
    _is_debug_url,
    _quote,
    _remaining,
    _required_string,
    _verify_debug_service,
)


@dataclass(frozen=True)
class RustyCrewNativeConfig:
    base_url: str
    provider_alias: str
    local_tool_profile_id: str
    brain_module: str | None
    brain_strategy: str | None
    task: str
    service_unit: str
    require_debug_service: bool
    auth_token_env: str | None
    poll_interval_seconds: float
    cleanup_profile: bool

    @classmethod
    def from_candidate(cls, candidate: CandidateConfig) -> "RustyCrewNativeConfig":
        cfg = candidate.config
        base_url = str(cfg.get("base_url") or candidate.base_url or DEFAULT_DEBUG_BASE_URL).rstrip("/")
        provider_alias = str(cfg.get("provider_alias") or "").strip()
        if not provider_alias:
            raise ValueError("candidate.config.provider_alias is required for rusty-crew-native runner")
        require_debug = bool(cfg.get("require_debug_service", True))
        if require_debug and not _is_debug_url(base_url):
            raise ValueError(
                f"rusty-crew-native runner refuses non-debug endpoint {base_url!r}; "
                "use the rusty-crew-debug.service endpoint on 127.0.0.1:9348"
            )
        poll_interval = float(cfg.get("poll_interval_seconds", 0.25))
        if poll_interval <= 0:
            raise ValueError("candidate.config.poll_interval_seconds must be positive")
        return cls(
            base_url=base_url,
            provider_alias=provider_alias,
            local_tool_profile_id=str(cfg.get("local_tool_profile_id") or "full_agent"),
            brain_module=_optional_string(cfg.get("brain_module")),
            brain_strategy=_optional_string(cfg.get("brain_strategy")),
            task=str(cfg.get("task") or ""),
            service_unit=str(cfg.get("service_unit") or DEFAULT_DEBUG_SERVICE_UNIT),
            require_debug_service=require_debug,
            auth_token_env=str(cfg.get("auth_token_env")) if cfg.get("auth_token_env") else None,
            poll_interval_seconds=poll_interval,
            cleanup_profile=bool(cfg.get("cleanup_profile", True)),
        )


class RustyCrewNativeRunner:
    name = "rusty-crew-native"

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
        client: RustyCrewClient | None = None
        created_profile_id: str | None = None
        cleanup: dict[str, Any] = {"requested": True, "status": "not_needed"}

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
                environment=environment or {
                    "lane": "environment-realized",
                    "name": "rusty-crew-debug",
                    "cleanup": cleanup,
                },
            )

        try:
            cfg = RustyCrewNativeConfig.from_candidate(candidate)
            cleanup["requested"] = cfg.cleanup_profile
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
            fixture_abs = os.path.abspath(fixture_dest)
            before = snapshot_directory(fixture_dest, SKIP_DIRS_AGENT)
            workspace_hash = snapshot_sha256(before)
            task = _native_task_with_locality_contract(task, fixture_abs, candidate.system_prompt)
            trace.append(TraceEvent(now_iso(), "rusty_crew_native.fixture.copied", {
                "source": fixture_source, "destination": fixture_dest, "workspace_sha256": workspace_hash,
            }))

            timeout_seconds = float(timeout if timeout is not None else (scenario.timeout_seconds or 300))
            deadline = time.monotonic() + timeout_seconds
            token = os.environ.get(cfg.auth_token_env) if cfg.auth_token_env else None
            client = RustyCrewClient(cfg.base_url, token)
            identity = _safe_identity(context.run_id, scenario.id, candidate.id)
            created_profile_id = f"gb-{identity}"[:120]
            profile_body: dict[str, Any] = {
                "profileId": created_profile_id,
                "displayName": f"GoblinBench {scenario.id} / {candidate.id}",
                "providerAlias": cfg.provider_alias,
                "kind": "full",
                "localToolProfileId": cfg.local_tool_profile_id,
                "reason": "isolated GoblinBench native-brain cell",
            }
            brain = {key: value for key, value in {
                "module": cfg.brain_module, "strategy": cfg.brain_strategy,
            }.items() if value is not None}
            if brain:
                profile_body["brain"] = brain
            creation = _dict(client.post(
                "/v1/admin/control/profiles", profile_body, _remaining(deadline),
                {"Idempotency-Key": f"{identity}:profile"},
            ))
            outcome = _dict(creation.get("outcome"))
            if outcome.get("status") != "completed":
                raise RustyCrewApiError(f"native profile creation failed: {outcome}")
            created = _dict(outcome.get("result"))
            session_id = _required_string(created, "sessionId")
            agent_id = _required_string(created, "agentId")
            trace.append(TraceEvent(now_iso(), "rusty_crew_native.profile.created", {
                "profile_id": created_profile_id, "session_id": session_id,
                "provider_alias": cfg.provider_alias,
            }))

            profile = _dict(client.get(
                f"/v1/admin/profiles/registry/{_quote(created_profile_id)}", _remaining(deadline)
            ))
            if profile.get("profileId") != created_profile_id:
                raise RustyCrewApiError(
                    f"Rusty Crew returned the wrong native profile after creation: {profile.get('profileId')!r}"
                )
            session_open = _dict(client.get(f"/v1/chat/sessions/{_quote(session_id)}", _remaining(deadline)))
            session_summary = _dict(session_open.get("session"))
            session_workdir = _dict(_dict(session_summary.get("effective_defaults")).get("resourceLimits")).get("workdir")
            session_context = _dict(client.get(
                f"/v1/chat/sessions/{_quote(session_id)}/context", _remaining(deadline)
            ))
            provider = _dict(session_context.get("provider"))
            brain_context = _dict(session_context.get("brain"))
            tools = _dict(session_context.get("tools"))
            resolved_model = str(provider.get("model_id") or candidate.model or "unknown")
            protocol = str(provider.get("protocol") or "unknown")
            _validate_native_resolution(candidate, cfg, provider, brain_context, resolved_model)
            wake_path = f"/v1/chat/sessions/{_quote(session_id)}/messages"
            delivery_key = f"{identity}:message"
            delivery = _dict(client.post(wake_path, {
                "actor": {"id": "goblinbench", "kind": "human", "display_name": "GoblinBench"},
                "body": task,
                "client_message_id": delivery_key[:200],
                "reason": "GoblinBench isolated native-brain evaluation",
            }, _remaining(deadline), {"Idempotency-Key": delivery_key}))
            if delivery.get("status") not in {"accepted", "duplicate"}:
                raise RustyCrewApiError(f"native chat message was not accepted: {delivery}")
            wake_id = _required_string(delivery, "wake_id")
            message_id = _required_string(delivery, "message_id")
            cursor = str(delivery.get("latest_cursor") or f"{session_id}:0")
            events = _wait_for_native_turn(
                client, session_id, cursor, wake_id, deadline, cfg.poll_interval_seconds
            )
            debug_details = _native_tool_debug_details(client, session_id, wake_id, events, deadline)
            events_truncated = _write_jsonl_bounded(
                artifact_dir / "rusty-crew-native-events.jsonl", events
            )
            debug_truncated = _write_jsonl_bounded(
                artifact_dir / "rusty-crew-native-tool-details.jsonl", debug_details
            )
            assistant_text = _native_assistant_text(events, wake_id)
            (artifact_dir / "rusty-crew-native-response.txt").write_text(
                assistant_text, encoding="utf-8"
            )

            after = snapshot_directory(fixture_dest, SKIP_DIRS_AGENT)
            diff = compute_unified_diff(before, after, fixture_dest)
            (artifact_dir / "agent.patch").write_text(diff.unified_diff_text, encoding="utf-8")
            terminal = _native_terminal(events, wake_id)
            completed = terminal == "completed"
            produced_changes = bool(diff.files_changed)
            locality = _native_locality_evidence(debug_details, fixture_abs)
            tool_calls = len({
                _dict(event.get("payload")).get("tool_call_id")
                for event in events
                if event.get("kind") == "tool_call_started"
                and _dict(event.get("payload")).get("wake_id") == wake_id
            } - {None})

            cleanup = _cleanup_native_profile(client, cfg, created_profile_id, time.monotonic() + 30)
            created_profile_id = None
            if not completed:
                error = f"Rusty Crew native wake completed with status {terminal!r}."
            elif not locality["passed"]:
                error = f"Rusty Crew native locality check failed: {locality['violations']}"
            elif not produced_changes:
                error = "Rusty Crew native wake completed but produced no fixture file changes."
            elif cleanup.get("status") != "completed":
                error = f"Rusty Crew native profile cleanup failed: {cleanup.get('error')}"
            else:
                error = None
            duration_ms = int((time.perf_counter() - started) * 1000)
            tool_identity = {
                "localToolProfileId": profile.get("localToolProfileId"),
                "toolPolicy": profile.get("toolPolicy"),
                "mcpBindings": profile.get("mcpBindings"),
            }
            environment = {
                "lane": "environment-realized",
                "name": "rusty-crew-debug",
                "model": {
                    "requested": candidate.model,
                    "resolved": resolved_model,
                    "provider_requested": cfg.provider_alias,
                    "provider_resolved": provider.get("alias"),
                    "provider_kind": provider.get("provider_kind"),
                    "provider_protocol": protocol,
                    "provider_revision": provider.get("revision"),
                    "requested_reasoning_effort": candidate.config.get("reasoning_effort"),
                    "reasoning_effort": provider.get("reasoning_effort"),
                },
                "substrate": {
                    "kind": "rusty-crew-native-brain",
                    "name": cfg.service_unit,
                    "transport": "http-chat-events",
                    "base_url": cfg.base_url,
                    "brain_module": brain_context.get("module"),
                    "brain_strategy": brain_context.get("strategy"),
                    "brain_backend": brain_context.get("backend"),
                },
                "profile": {
                    "id": profile.get("profileId"),
                    "revision": profile.get("revision"),
                    "role": profile.get("displayName"),
                    "prompt_assembly_id": profile.get("providerAlias"),
                    "tool_catalog_sha256": json_sha256(tool_identity),
                    "local_tool_profile_id": tools.get("local_tool_profile_id"),
                    "tool_count": tools.get("tool_count"),
                },
                "harness": {
                    "family": f"crew-native-{protocol.replace('_completions', '')}",
                    "workspace_sha256": workspace_hash,
                    "session_workdir": session_workdir,
                    "locality": locality,
                    "event_artifact_truncated": events_truncated,
                    "tool_detail_artifact_truncated": debug_truncated,
                    "sandbox": "crew-native-local-tools",
                    "known_limit_task_id": 5846 if session_workdir != fixture_abs else None,
                },
                "execution": {
                    "runner_status": "completed" if error is None else "failed",
                    "substrate_status": terminal,
                    "terminal_status": terminal,
                    "retries": 0,
                    "tool_calls": tool_calls,
                    "command_cycles": sum(
                        1 for detail in debug_details if detail.get("tool_name") == "terminal"
                    ),
                    "configuration_commands": 0,
                },
                "usage": {
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "output_tokens": None,
                    "reasoning_output_tokens": None,
                    "total_tokens": None,
                    "model_context_window": provider.get("context_window_tokens"),
                    "classification": "not_exposed_by_native_chat_events",
                },
                "cost": {
                    "classification": "unavailable",
                    "amount": None,
                    "currency": None,
                    "basis": "Rusty Crew native chat API does not expose attributable run cost",
                },
                "identifiers": {
                    "profile_id": profile.get("profileId"),
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "message_id": message_id,
                    "wake_id": wake_id,
                },
                "cleanup": cleanup,
            }
            trace.append(TraceEvent(now_iso(), "rusty_crew_native.completed", {
                "profile_id": profile.get("profileId"), "session_id": session_id,
                "wake_id": wake_id, "status": terminal,
                "files_changed": len(diff.files_changed), "duration_ms": duration_ms,
                "cleanup_status": cleanup.get("status"),
            }))
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=ModelIdentity(
                    model=resolved_model,
                    provider=str(provider.get("alias") or cfg.provider_alias),
                    base_url=cfg.base_url,
                    display_name=f"rusty-crew-native:{cfg.provider_alias}:{resolved_model}",
                ),
                success=error is None,
                error=error,
                duration_ms=duration_ms,
                raw_response=assistant_text[:MAX_RESPONSE_CHARS],
                output={
                    "fixture_dir": fixture_dest,
                    "fixture_case": fixture_case,
                    "patch": diff.unified_diff_text,
                    "files_changed": diff.files_changed,
                    "profile_id": profile.get("profileId"),
                    "session_id": session_id,
                    "message_id": message_id,
                    "wake_id": wake_id,
                    "turn_status": terminal,
                    "requested_model": candidate.model,
                    "resolved_model": resolved_model,
                    "provider_alias": cfg.provider_alias,
                    "provider_protocol": protocol,
                    "brain_module": brain_context.get("module"),
                    "brain_strategy": brain_context.get("strategy"),
                    "locality": locality,
                    "timed_out": False,
                },
                trace=trace,
                artifact_directory=str(artifact_dir),
                environment=environment,
            )
        except Exception as exc:  # noqa: BLE001
            cleanup_error = None
            if client is not None and created_profile_id is not None:
                try:
                    cleanup = _cleanup_native_profile(
                        client, cfg, created_profile_id, time.monotonic() + 30  # type: ignore[possibly-undefined]
                    )
                    created_profile_id = None
                except Exception as cleanup_exc:  # noqa: BLE001
                    cleanup_error = str(cleanup_exc)
                    cleanup = {"requested": True, "status": "failed", "error": cleanup_error}
            suffix = f"; cleanup failed: {cleanup_error}" if cleanup_error else ""
            return fail(f"RustyCrewNativeRunner failed: {exc}{suffix}")


def _wait_for_native_turn(
    client: RustyCrewClient,
    session_id: str,
    cursor: str,
    wake_id: str,
    deadline: float,
    poll_interval: float,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        page = _dict(client.get(
            f"/v1/chat/sessions/{_quote(session_id)}/events?cursor={_quote(cursor)}&limit=500",
            _remaining(deadline),
        ))
        fresh = [_dict(event) for event in page.get("items") or []]
        if fresh:
            events.extend(fresh)
            cursor = str(fresh[-1].get("event_id") or page.get("latest_cursor") or cursor)
        matching_terminal = [
            event for event in events
            if event.get("kind") in {"assistant_message_completed", "stream_error"}
            and _dict(event.get("payload")).get("wake_id") in {None, wake_id}
        ]
        if matching_terminal and not page.get("has_more"):
            return events
        if fresh and page.get("has_more"):
            continue
        time.sleep(min(poll_interval, max(0.01, _remaining(deadline))))
    raise TimeoutError("timed out waiting for Rusty Crew native wake")


def _native_tool_debug_details(
    client: RustyCrewClient,
    session_id: str,
    wake_id: str,
    events: list[dict[str, Any]],
    deadline: float,
) -> list[dict[str, Any]]:
    detail_ids: list[str] = []
    for event in events:
        payload = _dict(event.get("payload"))
        detail_id = payload.get("debug_detail_id")
        if payload.get("wake_id") == wake_id and isinstance(detail_id, str) and detail_id not in detail_ids:
            detail_ids.append(detail_id)
    details: list[dict[str, Any]] = []
    for detail_id in detail_ids:
        try:
            detail = _dict(client.get(
                f"/v1/chat/sessions/{_quote(session_id)}/tool-calls/{_quote(detail_id)}",
                _remaining(deadline),
            ))
            details.append(detail)
        except RustyCrewApiError as exc:
            details.append({"debug_detail_id": detail_id, "status": "unavailable", "error": str(exc)})
    return details


def _native_assistant_text(events: list[dict[str, Any]], wake_id: str) -> str:
    value = "".join(
        str(_dict(event.get("payload")).get("text") or "")
        for event in events
        if event.get("kind") == "assistant_text_delta"
        and _dict(event.get("payload")).get("wake_id") == wake_id
    )
    return value[:MAX_RESPONSE_CHARS] + ("\n...[truncated]" if len(value) > MAX_RESPONSE_CHARS else "")


def _native_terminal(events: list[dict[str, Any]], wake_id: str) -> str:
    for event in reversed(events):
        payload = _dict(event.get("payload"))
        if payload.get("wake_id") not in {None, wake_id}:
            continue
        if event.get("kind") == "assistant_message_completed":
            return str(payload.get("status") or "completed")
        if event.get("kind") == "stream_error":
            return "failed"
    return "unknown"


def _native_locality_evidence(details: list[dict[str, Any]], fixture_dir: str) -> dict[str, Any]:
    fixture = os.path.abspath(fixture_dir)
    inspected: list[dict[str, Any]] = []
    violations: list[str] = []
    probe_observed = False
    for detail in details:
        tool_name = str(detail.get("tool_name") or "")
        debug_value = _dict(_dict(detail.get("arguments")).get("value"))
        arguments = _dict(debug_value.get("preparedArguments")) or _dict(debug_value.get("rawArguments")) or debug_value
        retained_arguments = {
            key: arguments[key] for key in ("command", "path", "root") if key in arguments
        }
        record: dict[str, Any] = {"tool_name": tool_name, "arguments": retained_arguments}
        inspected.append(record)
        if tool_name == "terminal":
            command = arguments.get("command")
            if not isinstance(command, str):
                violations.append("terminal call missing textual command")
                continue
            prefix = f"cd {shlex.quote(fixture)} && "
            record["required_prefix"] = prefix
            if not command.startswith(prefix):
                violations.append(f"terminal command did not enter fixture first: {command}")
            if command == prefix + "pwd":
                probe_observed = True
        for key in ("path", "root"):
            value = arguments.get(key)
            if not isinstance(value, str):
                continue
            resolved = os.path.abspath(value if os.path.isabs(value) else os.path.join("/home", value))
            if os.path.commonpath([resolved, fixture]) != fixture:
                violations.append(f"{tool_name}.{key} resolved outside fixture: {value}")
    if not probe_observed:
        violations.append("required terminal fixture pwd probe was not observed")
    unavailable = [detail.get("debug_detail_id") for detail in details if detail.get("status") == "unavailable"]
    if unavailable:
        violations.append(f"tool debug details unavailable: {unavailable}")
    return {
        "required_fixture_dir": fixture,
        "probe_observed": probe_observed,
        "inspected_tool_calls": inspected,
        "tool_detail_count": len(details),
        "violations": violations,
        "passed": probe_observed and not violations,
    }


def _cleanup_native_profile(
    client: RustyCrewClient,
    cfg: RustyCrewNativeConfig,
    profile_id: str,
    deadline: float,
) -> dict[str, Any]:
    if not cfg.cleanup_profile:
        return {"requested": False, "status": "skipped", "profile_id": profile_id}
    try:
        data = _dict(client.post(
            f"/v1/admin/control/profiles/{_quote(profile_id)}/delete",
            {"confirmProfileId": profile_id, "reason": "GoblinBench native cell cleanup"},
            _remaining(deadline),
        ))
        outcome = _dict(data.get("outcome"))
        if outcome.get("status") != "completed":
            raise RustyCrewApiError(f"profile delete did not complete: {outcome}")
        return {"requested": True, "status": "completed", "profile_id": profile_id}
    except Exception as exc:  # noqa: BLE001
        return {"requested": True, "status": "failed", "profile_id": profile_id, "error": str(exc)}


def _native_task_with_locality_contract(task: str, fixture_dir: str, system_prompt: str | None) -> str:
    quoted = shlex.quote(os.path.abspath(fixture_dir))
    role = f"Benchmark role instructions:\n{system_prompt}\n\n" if system_prompt else ""
    return (
        f"{role}GoblinBench native execution-isolation contract:\n"
        f"Your only workspace is {fixture_dir}. Use absolute paths beneath it for every file tool. "
        f"Before any other tool call, call `terminal` with exactly `cd {quoted} && pwd`. "
        f"Every later terminal command must begin exactly `cd {quoted} && `. "
        "Do not inspect or change files outside the workspace.\n\n"
        f"{task}"
    )


def _validate_native_resolution(
    candidate: CandidateConfig,
    cfg: RustyCrewNativeConfig,
    provider: dict[str, Any],
    brain: dict[str, Any],
    resolved_model: str,
) -> None:
    if candidate.model and candidate.model != resolved_model:
        raise RustyCrewApiError(
            f"provider alias {cfg.provider_alias!r} resolved model {resolved_model!r}, "
            f"not requested candidate model {candidate.model!r}"
        )
    requested_effort = _optional_string(candidate.config.get("reasoning_effort"))
    resolved_effort = _optional_string(provider.get("reasoning_effort"))
    if requested_effort and requested_effort != resolved_effort:
        raise RustyCrewApiError(
            f"provider alias {cfg.provider_alias!r} resolved reasoning effort {resolved_effort!r}, "
            f"not requested {requested_effort!r}"
        )
    if cfg.brain_module and cfg.brain_module != brain.get("module"):
        raise RustyCrewApiError(
            f"native brain resolved module {brain.get('module')!r}, not requested {cfg.brain_module!r}"
        )
    if cfg.brain_strategy and cfg.brain_strategy != brain.get("strategy"):
        raise RustyCrewApiError(
            f"native brain resolved strategy {brain.get('strategy')!r}, not requested {cfg.brain_strategy!r}"
        )


def _write_jsonl_bounded(path: Path, values: list[dict[str, Any]]) -> bool:
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            line = dumps(value, indent=None) + "\n"
            size = len(line.encode("utf-8"))
            if written + size > MAX_EVENT_ARTIFACT_BYTES:
                handle.write(dumps({"event": "truncated", "max_bytes": MAX_EVENT_ARTIFACT_BYTES}, indent=None) + "\n")
                return True
            handle.write(line)
            written += size
    return False


def _safe_identity(run_id: str, scenario_id: str, candidate_id: str) -> str:
    raw = "-".join((run_id, scenario_id, candidate_id)).lower()
    value = "".join(ch if ch.isalnum() else "-" for ch in raw)
    return "-".join(part for part in value.split("-") if part)[:110]


def _optional_string(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None
