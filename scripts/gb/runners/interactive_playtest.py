"""First-class Rusty Crew vision playtest runner.

The runner is intentionally separate from the coding/text native runner.  It
creates a disposable native Crew profile whose only model-facing browser
surface is ``vision_playtester``, sends one bounded mission, and retains the
broker's authoritative evidence index.  Product outcomes (including a valid
``fail`` report) are not runner errors; contract validity and pairwise labels
are assigned by :mod:`gb.playtest_evidence`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import RunContext
from ..environment import json_sha256
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..playtest_evidence import (
    PLAYTEST_OUTCOMES,
    REQUIRED_LOCAL_TOOL_PROFILE,
    archive_selected_evidence,
)
from ..serialize import dumps, now_iso
from .rusty_crew import (
    DEFAULT_DEBUG_BASE_URL,
    DEFAULT_DEBUG_SERVICE_UNIT,
    MAX_RESPONSE_CHARS,
    RustyCrewApiError,
    RustyCrewClient,
    _activity_counts,
    _dict,
    _quote,
    _remaining,
    _required_string,
    _usage,
    _verify_debug_service,
)
from .rusty_crew_native import (
    _apply_native_reasoning_effort,
    _cleanup_native_profile,
    _native_assistant_text,
    _native_observed_tool_calls,
    _native_provider_debug_details,
    _native_terminal,
    _native_tool_debug_details,
    _wait_for_native_turn,
    _write_jsonl_bounded,
)


_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_FORBIDDEN_SCENARIO_OVERRIDES = {
    "mission",
    "controls",
    "manifest_path",
    "viewport",
    "headed",
    "record_video",
    "budget",
    "max_actions",
    "max_session_minutes",
}


@dataclass(frozen=True)
class InteractivePlaytestConfig:
    base_url: str
    provider_alias: str
    expected_protocol: str | None
    reasoning_effort: str | None
    local_tool_profile_id: str
    service_unit: str
    require_debug_service: bool
    auth_token_env: str | None
    poll_interval_seconds: float
    cleanup_profile: bool
    prequalified: bool
    prequalification_evidence: dict[str, Any]
    repo_root: str | None
    archive_root: str | None
    pair_role: str | None
    pair_id: str | None
    max_infrastructure_retries: int

    @classmethod
    def from_candidate(cls, candidate: CandidateConfig) -> "InteractivePlaytestConfig":
        cfg = candidate.config
        forbidden = sorted(key for key in _FORBIDDEN_SCENARIO_OVERRIDES if key in cfg)
        if forbidden:
            raise ValueError(
                "interactive-playtest mission, manifest, viewport, and budgets are scenario-owned; "
                f"remove candidate overrides {forbidden}"
            )
        base_url = str(cfg.get("base_url") or candidate.base_url or DEFAULT_DEBUG_BASE_URL).rstrip("/")
        require_debug = bool(cfg.get("require_debug_service", True))
        if require_debug and (not base_url.startswith("http://127.0.0.1:9348") and not base_url.startswith("http://localhost:9348")):
            raise ValueError(
                f"interactive-playtest runner refuses non-debug endpoint {base_url!r}; "
                "use rusty-crew-debug.service on 127.0.0.1:9348"
            )
        provider_alias = str(cfg.get("provider_alias") or "").strip()
        if not provider_alias:
            raise ValueError("candidate.config.provider_alias is required for interactive-playtest runner")
        local_profile = str(cfg.get("local_tool_profile_id") or REQUIRED_LOCAL_TOOL_PROFILE).strip()
        if local_profile != REQUIRED_LOCAL_TOOL_PROFILE:
            raise ValueError(
                f"interactive-playtest runner requires local_tool_profile_id={REQUIRED_LOCAL_TOOL_PROFILE!r}"
            )
        if cfg.get("prequalified") is not True:
            raise ValueError(
                "interactive-playtest candidate must declare prequalified=true after image-input, "
                "multi-turn tooling, and vision_playtester lifecycle screening"
            )
        admission = cfg.get("prequalification")
        if not isinstance(admission, dict):
            raise ValueError(
                "interactive-playtest candidate must retain a prequalification evidence object"
            )
        required_admission_checks = (
            "image_input",
            "multi_turn_tools",
            "restricted_profile",
            "lifecycle_cleanup",
            "identity_readback",
        )
        missing_admission = [
            key for key in required_admission_checks if admission.get(key) is not True
        ]
        evidence_ref = admission.get("evidence_ref")
        if missing_admission or not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise ValueError(
                "interactive-playtest candidate prequalification must retain evidence_ref and "
                f"all live checks {required_admission_checks}; missing={missing_admission}"
            )
        poll = float(cfg.get("poll_interval_seconds", 0.25))
        if poll <= 0:
            raise ValueError("candidate.config.poll_interval_seconds must be positive")
        effort = cfg.get("reasoning_effort")
        if effort is not None:
            if not isinstance(effort, str) or not effort.strip():
                raise ValueError("candidate.config.reasoning_effort must be a non-empty token")
            effort = effort.strip()
        return cls(
            base_url=base_url,
            provider_alias=provider_alias,
            expected_protocol=str(cfg.get("provider_protocol")) if cfg.get("provider_protocol") else None,
            reasoning_effort=effort,
            local_tool_profile_id=local_profile,
            service_unit=str(cfg.get("service_unit") or DEFAULT_DEBUG_SERVICE_UNIT),
            require_debug_service=require_debug,
            auth_token_env=str(cfg.get("auth_token_env")) if cfg.get("auth_token_env") else None,
            poll_interval_seconds=poll,
            cleanup_profile=bool(cfg.get("cleanup_profile", True)),
            prequalified=True,
            prequalification_evidence={str(key): value for key, value in admission.items()},
            repo_root=str(cfg.get("repo_root")) if cfg.get("repo_root") else None,
            archive_root=str(cfg.get("archive_root")) if cfg.get("archive_root") else None,
            pair_role=str(cfg.get("pair_role")) if cfg.get("pair_role") else None,
            pair_id=str(cfg.get("pair_id")) if cfg.get("pair_id") else None,
            max_infrastructure_retries=max(0, min(1, int(cfg.get("max_infrastructure_retries", 1)))),
        )


class InteractivePlaytestRunner:
    name = "interactive-playtest"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return (
            candidate.kind is not None
            and candidate.kind.value in {"CodingAgent", "OpenAiModel"}
            and str(candidate.config.get("runner") or "").strip().lower() == self.name
        )

    def run(
        self,
        scenario: Scenario,
        candidate: CandidateConfig,
        context: RunContext,
        timeout: float | None = None,
    ) -> CandidateResult:
        """Run once, retrying one plausibly transient infrastructure failure."""

        configured_retries = candidate.config.get("max_infrastructure_retries", 1)
        try:
            max_retries = max(0, min(1, int(configured_retries)))
        except (TypeError, ValueError):
            max_retries = 0
        attempts: list[dict[str, Any]] = []
        for attempt in range(max_retries + 1):
            attempt_context = RunContext(
                run_id=context.run_id,
                started_at=context.started_at,
                run_directory=context.run_directory,
                runs_root=context.runs_root,
                repo_root=context.repo_root,
                scenario_id=context.scenario_id,
                label=context.label,
                metadata={**context.metadata, "interactive_playtest_attempt": attempt},
            )
            result = self._run_once(scenario, candidate, attempt_context, timeout)
            attempts.append({"attempt": attempt, "success": result.success, "error": result.error})
            if result.success or attempt >= max_retries or not _retryable_infrastructure_error(result.error):
                output = result.output if isinstance(result.output, dict) else {}
                output["retry"] = {"attempts": attempts, "max_retries": max_retries}
                result.output = output
                return result
        raise AssertionError("interactive playtest retry loop did not return")

    def _run_once(
        self,
        scenario: Scenario,
        candidate: CandidateConfig,
        context: RunContext,
        timeout: float | None = None,
    ) -> CandidateResult:
        started = time.perf_counter()
        trace: list[TraceEvent] = []
        artifact_dir = Path(context.candidate_artifacts_directory(candidate.id))
        artifact_dir.mkdir(parents=True, exist_ok=True)
        client: RustyCrewClient | None = None
        created_profile_id: str | None = None
        cleanup: dict[str, Any] = {"requested": True, "status": "not_needed"}
        cfg: InteractivePlaytestConfig | None = None
        target: dict[str, Any] = {}
        broker_session_id: str | None = None
        crew_session_id: str | None = None
        wake_id: str | None = None
        event_cursor: str | None = None

        def fail(error: str, environment: dict[str, Any] | None = None) -> CandidateResult:
            failure_evidence = {
                "session_id": broker_session_id or "",
                "finish_outcome": "infrastructure_error",
                "cell_id": target.get("cell_id"),
                "cell_class": target.get("cell_class"),
                "mutation_proof": target.get("mutation_proof"),
                "mutation_proof_path": target.get("mutation_proof_path"),
                "mutation_proof_sha256": target.get("mutation_proof_sha256"),
                "defect_family": target.get("defect_family"),
                "campaign_id": target.get("campaign_id"),
                "repetition": target.get("repetition"),
                "pair_id": target.get("pair_id"),
                "pair_role": target.get("pair_role"),
                "expected_revision": target.get("expected_revision"),
            }
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                success=False,
                error=error,
                duration_ms=int((time.perf_counter() - started) * 1000),
                trace=trace,
                output={"target": target, "cleanup": cleanup, "playtest_evidence": failure_evidence},
                artifact_directory=str(artifact_dir),
                environment=environment or {
                    "lane": "environment-realized",
                    "name": "rusty-crew-debug",
                    "cleanup": cleanup,
                    "playtest_target": target,
                },
            )

        try:
            cfg = InteractivePlaytestConfig.from_candidate(candidate)
            cleanup["requested"] = cfg.cleanup_profile
            if cfg.require_debug_service:
                _verify_debug_service(cfg.service_unit)
            target = _resolve_target(scenario, cfg)
            _verify_target_revision(target)
            mission = _render_mission(scenario, candidate, target, cfg)
            timeout_seconds = float(timeout if timeout is not None else (scenario.timeout_seconds or 600))
            deadline = time.monotonic() + timeout_seconds
            token = os.environ.get(cfg.auth_token_env) if cfg.auth_token_env else None
            client = RustyCrewClient(cfg.base_url, token)
            identity = _safe_identity(
                context.run_id,
                scenario.id,
                candidate.id,
                int(context.metadata.get("interactive_playtest_attempt", 0)),
            )
            created_profile_id = f"gb-{identity}-playtest"[:120]
            profile_body: dict[str, Any] = {
                "profileId": created_profile_id,
                "displayName": f"GoblinBench {scenario.id} / {candidate.id}",
                "providerAlias": cfg.provider_alias,
                "kind": "full",
                "localToolProfileId": cfg.local_tool_profile_id,
                "reason": "isolated GoblinBench interactive playtest cell",
            }
            creation = _dict(client.post(
                "/v1/admin/control/profiles",
                profile_body,
                _remaining(deadline),
                {"Idempotency-Key": f"{identity}:profile"},
            ))
            outcome = _dict(creation.get("outcome"))
            if outcome.get("status") != "completed":
                raise RustyCrewApiError(f"interactive playtest profile creation failed: {outcome}")
            created = _dict(outcome.get("result"))
            agent_id = _required_string(created, "agentId")
            session_id = f"{created_profile_id}-benchmark"[:160]
            crew_session_id = session_id
            session_creation = _dict(client.post(
                "/v1/admin/control/sessions",
                {
                    "sessionId": session_id,
                    "agentId": agent_id,
                    "profileId": created_profile_id,
                    "kind": "full",
                    "resourceLimits": {
                        "workdir": target["repo_root"],
                        "maxDurationMs": max(1, int(timeout_seconds * 1000)),
                        "maxDelegationDepth": 0,
                    },
                    "reason": "isolated GoblinBench interactive playtest session",
                },
                _remaining(deadline),
                {"Idempotency-Key": f"{identity}:session"},
            ))
            session_outcome = _dict(session_creation.get("outcome"))
            if session_outcome.get("status") != "completed":
                raise RustyCrewApiError(f"interactive playtest session creation failed: {session_outcome}")
            session_created = _dict(session_outcome.get("result"))
            if session_created.get("sessionId") not in {None, session_id}:
                raise RustyCrewApiError(
                    f"Rusty Crew returned the wrong interactive playtest session: "
                    f"{session_created.get('sessionId')!r}"
                )

            effort_control = _apply_native_reasoning_effort(
                client, session_id, cfg.reasoning_effort, identity, deadline
            )
            profile = _dict(client.get(
                f"/v1/admin/profiles/registry/{_quote(created_profile_id)}", _remaining(deadline)
            ))
            session_open = _dict(client.get(f"/v1/chat/sessions/{_quote(session_id)}", _remaining(deadline)))
            session_summary = _dict(session_open.get("session"))
            session_workdir = _dict(_dict(session_summary.get("effective_defaults")).get("resourceLimits")).get("workdir")
            if os.path.abspath(str(session_workdir or "")) != target["repo_root"]:
                raise RustyCrewApiError(
                    f"interactive playtest session workdir {session_workdir!r} did not match target {target['repo_root']!r}"
                )
            session_context = _dict(client.get(
                f"/v1/chat/sessions/{_quote(session_id)}/context", _remaining(deadline)
            ))
            provider = _dict(session_context.get("provider"))
            tools = _dict(session_context.get("tools"))
            resolved_model = str(provider.get("model_id") or candidate.model or "unknown")
            resolved_protocol = str(provider.get("protocol") or "unknown")
            _validate_resolution(candidate, cfg, provider, tools, resolved_model)
            _validate_effort_readback(cfg, provider)
            if profile.get("localToolProfileId") != cfg.local_tool_profile_id:
                raise RustyCrewApiError(
                    f"created profile readback localToolProfileId={profile.get('localToolProfileId')!r}"
                )
            _validate_profile_policy(profile, cfg.local_tool_profile_id)
            trace.append(TraceEvent(now_iso(), "interactive_playtest.session.ready", {
                "profile_id": created_profile_id,
                "session_id": session_id,
                "target_repo": target["repo_root"],
                "expected_revision": target["expected_revision"],
                "pair_id": target.get("pair_id"),
                "pair_role": target.get("pair_role"),
            }))
            delivery = _dict(client.post(
                f"/v1/chat/sessions/{_quote(session_id)}/messages",
                {
                    "actor": {"id": "goblinbench", "kind": "human", "display_name": "GoblinBench"},
                    "body": mission,
                    "client_message_id": f"{identity}:message"[:200],
                    "reason": "GoblinBench isolated interactive playtest evaluation",
                },
                _remaining(deadline),
                {"Idempotency-Key": f"{identity}:message"},
            ))
            if str(delivery.get("status") or "") not in {"accepted", "duplicate"}:
                raise RustyCrewApiError(f"interactive playtest mission was not accepted: {delivery}")
            wake_id = _required_string(delivery, "wake_id")
            message_id = _required_string(delivery, "message_id")
            cursor = str(delivery.get("latest_cursor") or f"{session_id}:0")
            event_cursor = cursor
            events = _wait_for_native_turn(
                client, session_id, cursor, wake_id, deadline, cfg.poll_interval_seconds
            )
            debug_details = _native_tool_debug_details(client, session_id, wake_id, events, deadline)
            provider_debug = _native_provider_debug_details(client, session_id, wake_id, events, deadline)
            events_truncated = _write_jsonl_bounded(
                artifact_dir / "rusty-crew-playtest-events.jsonl", events
            )
            debug_truncated = _write_jsonl_bounded(
                artifact_dir / "rusty-crew-playtest-tool-details.jsonl", debug_details
            )
            provider_truncated = _write_jsonl_bounded(
                artifact_dir / "rusty-crew-playtest-provider-requests.jsonl", provider_debug
            )
            assistant_text = _native_assistant_text(events, wake_id)
            (artifact_dir / "rusty-crew-playtest-response.txt").write_text(assistant_text, encoding="utf-8")
            tool_calls = _native_observed_tool_calls(debug_details)
            terminal = _native_terminal(events, wake_id)
            evidence = _extract_playtest_evidence(
                tool_calls,
                session_id=session_id,
                expected_revision=target["expected_revision"],
                cell_id=target["cell_id"],
                cell_class=target["cell_class"],
                mutation_proof=target.get("mutation_proof"),
                mutation_proof_path=target.get("mutation_proof_path"),
                mutation_proof_sha256=target.get("mutation_proof_sha256"),
                defect_family=target.get("defect_family"),
                campaign_id=target["campaign_id"],
                repetition=target["repetition"],
                mission_hash=hashlib.sha256(mission.encode("utf-8")).hexdigest(),
                acceptance_hash=hashlib.sha256(
                    json.dumps(
                        {
                            "cell_id": target["cell_id"],
                            "cell_class": target["cell_class"],
                            "defect_family": target.get("defect_family"),
                            "expected_outcome": scenario.input.get("expected_outcome"),
                        },
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest(),
                pair_id=target.get("pair_id"),
                pair_role=target.get("pair_role"),
            )
            # Only a playtest_start result is a broker session handle.  The
            # extractor falls back to the Crew session ID when start was
            # absent, and that ID must never be sent to den-playwright cancel.
            broker_session_id = _broker_session_id_from_tool_calls(tool_calls)
            index_path = evidence.get("evidence_index")
            if isinstance(index_path, str) and index_path:
                try:
                    evidence["evidence_index_sha256"] = hashlib.sha256(
                        Path(index_path).read_bytes()
                    ).hexdigest()
                except OSError:
                    evidence["evidence_index_sha256"] = None
            archive: dict[str, Any] | None = None
            if isinstance(index_path, str) and index_path:
                try:
                    archive_root = cfg.archive_root or str(Path(context.runs_root) / "evidence-archive")
                    archive = archive_selected_evidence(
                        index_path,
                        archive_root,
                        evidence.get("selected_artifacts") or [],
                    )
                    evidence["evidence_archive"] = archive
                    # Keep the authoritative index as a convenient cell
                    # artifact too; the archive is the durable copy.
                    source = Path(index_path)
                    if source.is_file() and source.stat().st_size <= 8 * 1024 * 1024:
                        (artifact_dir / "playtest-index.json").write_bytes(source.read_bytes())
                except (OSError, ValueError) as archive_error:
                    evidence["archive_error"] = str(archive_error)
            evidence["tool_calls"] = [
                {"tool_name": call.get("tool_name"), "arguments": call.get("arguments"), "status": call.get("status")}
                for call in tool_calls
            ]
            proof_path = target.get("mutation_proof_path")
            if isinstance(proof_path, str) and proof_path:
                try:
                    proof_source = Path(proof_path)
                    if proof_source.is_file() and proof_source.stat().st_size <= 2 * 1024 * 1024:
                        proof_name = "mutation-proof.json" if proof_source.suffix.lower() == ".json" else "mutation-proof.txt"
                        (artifact_dir / proof_name).write_bytes(proof_source.read_bytes())
                        evidence["mutation_proof_artifact"] = proof_name
                except OSError as proof_error:
                    evidence["mutation_proof_artifact_error"] = str(proof_error)
            (artifact_dir / "playtest-evidence.json").write_text(
                dumps(evidence), encoding="utf-8"
            )
            if broker_session_id and evidence.get("finish_outcome") not in PLAYTEST_OUTCOMES:
                cleanup["broker"] = _cancel_broker_session(candidate, broker_session_id)
            profile_cleanup = _cleanup_native_profile(client, cfg, created_profile_id, time.monotonic() + 30)
            if "broker" in cleanup:
                profile_cleanup["broker"] = cleanup["broker"]
            cleanup = profile_cleanup
            created_profile_id = None
            usage = _usage(events)
            activity_tool_count, command_count = _activity_counts(events)
            completed = terminal == "completed"
            cleanup_ok = cleanup.get("status") in {"completed", "skipped"}
            error = None
            if not completed:
                error = f"Rusty Crew interactive playtest turn completed with status {terminal!r}."
            elif not cleanup_ok:
                error = f"interactive playtest profile cleanup failed: {cleanup.get('error')}"
            environment = {
                "lane": "environment-realized",
                "name": "rusty-crew-debug",
                "model": {
                    "requested": candidate.model,
                    "resolved": resolved_model,
                    "provider_requested": cfg.provider_alias,
                    "provider_resolved": provider.get("alias"),
                    "provider_protocol": resolved_protocol,
                    "provider_revision": provider.get("revision"),
                    "requested_reasoning_effort": cfg.reasoning_effort,
                    "reasoning_effort": provider.get("reasoning_effort"),
                    "effort_control": effort_control,
                },
                "substrate": {
                    "kind": "rusty-crew-native-vision-playtest",
                    "name": cfg.service_unit,
                    "transport": "http-chat-events",
                    "base_url": cfg.base_url,
                },
                "profile": {
                    "id": profile.get("profileId"),
                    "revision": profile.get("revision"),
                    "role": profile.get("displayName"),
                    "prompt_assembly_id": profile.get("providerAlias"),
                    "tool_catalog_sha256": json_sha256({
                        "localToolProfileId": profile.get("localToolProfileId"),
                        "toolPolicy": profile.get("toolPolicy"),
                        "mcpBindings": profile.get("mcpBindings"),
                        "contextTools": tools,
                    }),
                    "local_tool_profile_id": tools.get("local_tool_profile_id") or profile.get("localToolProfileId"),
                    "tool_count": tools.get("tool_count"),
                    "requested_toolsets": tools.get("requested_toolsets"),
                    "requested_tools": tools.get("requested_tools"),
                    "mcp_binding_count": tools.get("mcp_binding_count"),
                    "mcp_active_count": tools.get("mcp_active_count"),
                    "prequalified": cfg.prequalified,
                    "prequalification_evidence": cfg.prequalification_evidence,
                },
                "harness": {
                    "target_repo": target["repo_root"],
                    "expected_revision": target["expected_revision"],
                    "session_workdir": session_workdir,
                    "event_artifact_truncated": events_truncated,
                    "tool_detail_artifact_truncated": debug_truncated,
                    "provider_debug_artifact_truncated": provider_truncated,
                    "sandbox": "crew-native-local-tools",
                    "pair_id": target.get("pair_id"),
                    "pair_role": target.get("pair_role"),
                },
                "execution": {
                    "runner_status": "completed" if error is None else "failed",
                    "substrate_status": terminal,
                    "terminal_status": terminal,
                    "tool_calls": activity_tool_count,
                    "command_cycles": command_count,
                    "configuration_commands": 1 if cfg.reasoning_effort is not None else 0,
                },
                "usage": usage | {"classification": "native-chat-events"},
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
                "playtest": {
                    "evidence_index": evidence.get("evidence_index"),
                    "evidence_archive": archive,
                    "finish_outcome": evidence.get("finish_outcome"),
                },
            }
            output = {
                "target": target,
                "session_id": session_id,
                "profile_id": profile.get("profileId"),
                "message_id": message_id,
                "wake_id": wake_id,
                "turn_status": terminal,
                "resolved_model": resolved_model,
                "provider_alias": cfg.provider_alias,
                "tool_calls": evidence.get("tool_calls"),
                "playtest_evidence": evidence,
                "evidence_archive": archive,
            }
            trace.append(TraceEvent(now_iso(), "interactive_playtest.completed", {
                "profile_id": profile.get("profileId"),
                "session_id": session_id,
                "wake_id": wake_id,
                "status": terminal,
                "finish_outcome": evidence.get("finish_outcome"),
                "evidence_index": evidence.get("evidence_index"),
            }))
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=ModelIdentity(
                    model=resolved_model,
                    provider=str(provider.get("alias") or cfg.provider_alias),
                    base_url=cfg.base_url,
                    display_name=f"interactive-playtest:{cfg.provider_alias}:{resolved_model}",
                ),
                success=error is None,
                error=error,
                duration_ms=int((time.perf_counter() - started) * 1000),
                raw_response=assistant_text,
                parsed_response=output,
                output=output,
                trace=trace,
                artifact_directory=str(artifact_dir),
                environment=environment,
            )
        except Exception as exc:  # noqa: BLE001 — one cell must not stop a matrix
            if broker_session_id is None and client is not None and crew_session_id and wake_id and event_cursor:
                # A timed-out/interrupted Crew turn may have started the broker
                # session without reaching playtest_finish.  Fetch one final
                # bounded event page so cleanup can still cancel that exact
                # broker session rather than leaving it orphaned.
                try:
                    page = _dict(client.get(
                        f"/v1/chat/sessions/{_quote(crew_session_id)}/events?cursor={_quote(event_cursor)}&limit=500",
                        5.0,
                    ))
                    partial_events = [_dict(event) for event in page.get("items") or []]
                    partial_details = _native_tool_debug_details(
                        client,
                        crew_session_id,
                        wake_id,
                        partial_events,
                        time.monotonic() + 5,
                    )
                    partial_calls = _native_observed_tool_calls(partial_details)
                    broker_session_id = _broker_session_id_from_tool_calls(partial_calls)
                except Exception:
                    broker_session_id = None
            broker_cleanup = _cancel_broker_session(candidate, broker_session_id) if broker_session_id else None
            cleanup_error = None
            if client is not None and created_profile_id is not None and cfg is not None:
                try:
                    cleanup = _cleanup_native_profile(
                        client, cfg, created_profile_id, time.monotonic() + 30
                    )
                    if broker_cleanup is not None:
                        cleanup["broker"] = broker_cleanup
                    created_profile_id = None
                except Exception as cleanup_exc:  # noqa: BLE001
                    cleanup_error = str(cleanup_exc)
                    cleanup = {"requested": True, "status": "failed", "error": cleanup_error}
            suffix = f"; cleanup failed: {cleanup_error}" if cleanup_error else ""
            return fail(f"InteractivePlaytestRunner failed: {exc}{suffix}")


def _resolve_target(scenario: Scenario, cfg: InteractivePlaytestConfig) -> dict[str, Any]:
    values = scenario.input
    repo_raw = cfg.repo_root or values.get("repo_root")
    if not repo_raw and values.get("repo_root_env"):
        repo_raw = os.environ.get(str(values["repo_root_env"]))
    if not isinstance(repo_raw, str) or not repo_raw.strip():
        raise ValueError("interactive-playtest target repo is missing; set scenario repo_root_env")
    repo_root = os.path.abspath(os.path.expanduser(repo_raw))
    if not os.path.isdir(repo_root):
        raise ValueError(f"interactive-playtest target repo does not exist: {repo_root}")
    cell_class = str(values.get("cell_class") or "").strip().lower()
    defect_family = str(values.get("defect_family") or "").strip() or None
    revision_env = (
        values.get("mutation_revision_env")
        if cell_class == "mutation"
        else values.get("expected_revision_env")
    )
    expected = values.get("expected_revision") or os.environ.get(str(revision_env or ""))
    if not isinstance(expected, str) or not _SHA_RE.fullmatch(expected.strip()):
        raise ValueError("interactive-playtest requires a full 40-character expected_revision")
    manifest = values.get("manifest_path") or "product-playtest.scenario.json"
    manifest_path = os.path.abspath(os.path.join(repo_root, str(manifest))) if not os.path.isabs(str(manifest)) else os.path.abspath(str(manifest))
    if not os.path.isfile(manifest_path):
        raise ValueError(f"interactive-playtest manifest does not exist: {manifest_path}")
    cell_id = str(values.get("cell_id") or "").strip()
    if not cell_id or cell_class not in {"known_good", "mutation"}:
        raise ValueError("interactive-playtest requires cell_id and cell_class=known_good|mutation")
    proof = values.get("mutation_proof")
    if not proof and values.get("mutation_proof_env"):
        proof = os.environ.get(str(values["mutation_proof_env"]))
    proof_path = values.get("mutation_proof_path") or os.environ.get(str(values.get("mutation_proof_path_env") or ""))
    if cell_class == "mutation" and (not isinstance(proof, str) or not proof.strip()):
        raise ValueError(
            f"mutation cell {cell_id!r} requires scorer-side mutation_proof or mutation_proof_env"
        )
    if proof_path and not os.path.isfile(os.path.abspath(os.path.expanduser(str(proof_path)))):
        raise ValueError(f"mutation proof path does not exist: {proof_path}")
    pair_id = str(values.get("pair_id") or cfg.pair_id or "").strip() or None
    pair_role = str(values.get("pair_role") or cfg.pair_role or "").strip().lower() or None
    campaign_id = str(values.get("campaign_id") or "goblinbench-6788-screen-v1").strip()
    try:
        repetition = int(values.get("repetition", 0))
    except (TypeError, ValueError):
        raise ValueError("interactive-playtest repetition must be an integer") from None
    if repetition < 0:
        raise ValueError("interactive-playtest repetition must be non-negative")
    if pair_id and pair_role not in {"incumbent", "challenger", "luna"}:
        raise ValueError("interactive-playtest pair_role must be incumbent, luna, or challenger")
    return {
        "repo_root": repo_root,
        "manifest_path": manifest_path,
        "expected_revision": expected.strip().lower(),
        "cell_id": cell_id,
        "cell_class": cell_class,
        "mutation_proof": str(proof).strip() if proof else None,
        "defect_family": defect_family,
        "mutation_proof_path": os.path.abspath(os.path.expanduser(str(proof_path))) if proof_path else None,
        "mutation_proof_sha256": (
            hashlib.sha256(
                Path(os.path.abspath(os.path.expanduser(str(proof_path)))).read_bytes()
            ).hexdigest()
            if proof_path
            else None
        ),
        "campaign_id": campaign_id,
        "repetition": repetition,
        "pair_id": pair_id,
        "pair_role": "incumbent" if pair_role == "luna" else pair_role,
    }


def _verify_target_revision(target: dict[str, Any]) -> None:
    try:
        actual = subprocess.run(
            ["git", "-C", target["repo_root"], "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip().lower()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"unable to read target Git revision: {exc}") from exc
    if actual != target["expected_revision"]:
        raise ValueError(
            f"target revision mismatch: requested {target['expected_revision']}, repository HEAD is {actual}"
        )
    try:
        dirty = subprocess.run(
            ["git", "-C", target["repo_root"], "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"unable to read target Git cleanliness: {exc}") from exc
    if dirty:
        raise ValueError(
            f"target corpus worktree is dirty at {actual}: {dirty.splitlines()[:8]}"
        )
    target["observed_revision"] = actual


def _render_mission(
    scenario: Scenario,
    candidate: CandidateConfig,
    target: dict[str, Any],
    cfg: InteractivePlaytestConfig,
) -> str:
    values = scenario.input
    manifest = _load_manifest(target["manifest_path"])
    mission = str(values.get("mission") or manifest.get("mission") or "").strip()
    if not mission:
        raise ValueError(
            "interactive-playtest requires a scenario/manifest neutral mission; "
            "scenario.description is never used because it may reveal the defect family"
        )
    controls = values.get("controls") or manifest.get("controls") or []
    rendered_controls: list[str] = []
    for control in controls:
        if isinstance(control, dict):
            rendered_controls.append(
                f"{control.get('input', 'visible input')}: {control.get('purpose', '')}".strip()
            )
        elif str(control).strip():
            rendered_controls.append(str(control).strip())
    budget = {
        "max_actions": int(values.get("max_actions", 40)),
        "max_session_minutes": float(values.get("max_session_minutes", 12)),
    }
    if values.get("max_estimated_cost_usd") is not None:
        budget["max_estimated_cost_usd"] = float(values["max_estimated_cost_usd"])
    artifact_policy = str(values.get("artifact_policy") or "Retain the authoritative playtest-index.json, screenshots/frame bursts, timeline, trace, and cleanup record.")
    lines = [
        "You are an operator and observer, not a fixer.",
        "Use only the restricted vision_playtester tools and the ordinary visible interface. Do not inspect source, DOM, application state, network, filesystem, or hidden readouts. Do not repair or reconfigure anything.",
        f"Project: {values.get('project') or scenario.id}",
        f"Repository revision identity supplied by the harness (do not infer product behavior from it): {target['expected_revision']}",
        f"Project manifest: {target['manifest_path']}",
        "",
        "Mission:",
        mission,
        "",
        "Supplied controls:",
        *[f"- {control}" for control in rendered_controls],
        "",
        "Budget:",
        f"- actions: {budget['max_actions']}",
        f"- session minutes: {budget['max_session_minutes']}",
        *([f"- estimated cost USD: {budget['max_estimated_cost_usd']}"] if "max_estimated_cost_usd" in budget else []),
        f"- artifact policy: {artifact_policy}",
        "",
        "Start with the exact revision and retain the returned evidence index. Alternate act and observe; use a sequence or frame burst for motion, handedness, collision, targeting, or transition claims. Make at most one bounded reproduction attempt when useful.",
        "Finish with playtest_finish using pass, fail, uncertain, or infrastructure_error. Include concise assertions whose artifact fields point to retained screenshots, frames, timeline, or the evidence index. Separate harness friction from product findings.",
    ]
    return "\n".join(lines)


def _load_manifest(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _extract_playtest_evidence(
    tool_calls: list[dict[str, Any]],
    *,
    session_id: str,
    expected_revision: str,
    cell_id: str,
    cell_class: str,
    mutation_proof: str | None,
    mutation_proof_path: str | None,
    mutation_proof_sha256: str | None,
    defect_family: str | None,
    campaign_id: str,
    repetition: int,
    mission_hash: str,
    acceptance_hash: str,
    pair_id: str | None,
    pair_role: str | None,
) -> dict[str, Any]:
    starts = [call for call in tool_calls if call.get("tool_name") == "playtest_start"]
    finishes = [call for call in tool_calls if call.get("tool_name") == "playtest_finish"]
    start_value = _unwrap_tool_result(starts[-1]) if starts else {}
    finish = finishes[-1] if finishes else {}
    finish_args = _dict(finish.get("arguments"))
    finish_value = _unwrap_tool_result(finish)
    finish_outcome = str(finish_args.get("outcome") or finish_value.get("status") or "").strip()
    defect_family_claim = (
        finish_args.get("defect_family_claim")
        or finish_args.get("claimed_defect_family")
        or finish_value.get("defect_family_claim")
        or finish_value.get("claimed_defect_family")
    )
    index_path = (
        finish_value.get("index_path")
        or finish_value.get("indexPath")
        or start_value.get("index_path")
        or start_value.get("indexPath")
    )
    evidence: dict[str, Any] = {
        "session_id": str(start_value.get("session_id") or start_value.get("sessionId") or session_id),
        "evidence_index": str(index_path) if isinstance(index_path, str) else "",
        "finish_outcome": finish_outcome,
        "assertions": finish_args.get("assertions") if isinstance(finish_args.get("assertions"), list) else [],
        "annotation": str(finish_args.get("annotation") or ""),
        "revision_binding": _dict(start_value.get("revision_binding") or start_value.get("revisionBinding")),
        "expected_revision": expected_revision,
        "cell_id": cell_id,
        "cell_class": cell_class,
        "mutation_proof": mutation_proof,
        "mutation_proof_path": mutation_proof_path,
        "mutation_proof_sha256": mutation_proof_sha256,
        "defect_family": defect_family,
        "defect_family_claim": str(defect_family_claim).strip() if isinstance(defect_family_claim, str) else "",
        "campaign_id": campaign_id,
        "repetition": repetition,
        "mission_hash": mission_hash,
        "acceptance_hash": acceptance_hash,
        "pair_id": pair_id,
        "pair_role": pair_role,
        "actions_used": finish_value.get("actions_used") or finish_value.get("actionsUsed"),
        "selected_artifacts": [],
    }
    for assertion in evidence["assertions"]:
        if isinstance(assertion, dict):
            artifact = assertion.get("artifact") or assertion.get("artifact_ref")
            if isinstance(artifact, str) and artifact.strip():
                evidence["selected_artifacts"].extend(
                    token.strip()
                    for token in artifact.split(";")
                    if token.strip()
                )
    return evidence


def _unwrap_tool_result(call: dict[str, Any]) -> dict[str, Any]:
    """Unwrap the native debug envelope around a tool's broker value.

    Rusty Crew stores the tool result as ``final_result.value.details``; the
    shared native helper preserves the command result under ``call.result``
    and its broker payload under ``call.result.value``. Replayed/fixture calls
    may already contain the payload directly, so accept both shapes without
    making the live path depend on one debug serialization.
    """

    value: Any = call.get("result")
    for _ in range(4):
        if not isinstance(value, dict):
            return {}
        nested = value.get("value")
        if isinstance(nested, dict):
            value = nested
            continue
        nested = value.get("details")
        if isinstance(nested, dict):
            value = nested
            continue
        nested = value.get("result")
        if isinstance(nested, dict):
            value = nested
            continue
        return value
    return value if isinstance(value, dict) else {}


def _broker_session_id_from_tool_calls(tool_calls: list[dict[str, Any]]) -> str | None:
    for call in reversed(tool_calls):
        if call.get("tool_name") != "playtest_start":
            continue
        value = _unwrap_tool_result(call)
        session = value.get("session_id") or value.get("sessionId")
        if isinstance(session, str) and session.strip():
            return session.strip()
    return None


def _validate_resolution(
    candidate: CandidateConfig,
    cfg: InteractivePlaytestConfig,
    provider: dict[str, Any],
    tools: dict[str, Any],
    resolved_model: str,
) -> None:
    if candidate.model and candidate.model != resolved_model:
        raise RustyCrewApiError(
            f"provider alias {cfg.provider_alias!r} resolved model {resolved_model!r}, not requested {candidate.model!r}"
        )
    protocol = str(provider.get("protocol") or "")
    if cfg.expected_protocol and cfg.expected_protocol != protocol:
        raise RustyCrewApiError(
            f"provider alias {cfg.provider_alias!r} resolved protocol {protocol!r}, not requested {cfg.expected_protocol!r}"
        )
    resolved_profile = tools.get("local_tool_profile_id") or tools.get("localToolProfileId")
    if resolved_profile != cfg.local_tool_profile_id:
        raise RustyCrewApiError(
            f"native chat context resolved local tool profile {resolved_profile!r}, not {cfg.local_tool_profile_id!r}"
        )
    requested_toolsets = tools.get("requested_toolsets") or tools.get("requestedToolsets")
    if requested_toolsets != [cfg.local_tool_profile_id]:
        raise RustyCrewApiError(
            f"native chat context requested toolsets {requested_toolsets!r}, "
            f"not [{cfg.local_tool_profile_id!r}]"
        )
    if tools.get("mcp_binding_count", 0) not in {0, None} or tools.get("mcp_active_count", 0) not in {0, None}:
        raise RustyCrewApiError("native chat context exposes MCP bindings to vision_playtester")
    if tools.get("tool_count") != 6:
        raise RustyCrewApiError(
            f"native chat context resolved {tools.get('tool_count')!r} tools; "
            "vision_playtester requires its exact six-tool catalog"
        )


def _validate_effort_readback(cfg: InteractivePlaytestConfig, provider: dict[str, Any]) -> None:
    if cfg.reasoning_effort is None:
        return
    expected = None if cfg.reasoning_effort == "default" else cfg.reasoning_effort
    if provider.get("session_reasoning_effort_override") != expected:
        raise RustyCrewApiError(
            f"interactive playtest effort override {provider.get('session_reasoning_effort_override')!r} did not match {expected!r}"
        )
    if expected is not None and provider.get("reasoning_effort") != expected:
        raise RustyCrewApiError(
            f"interactive playtest effective effort {provider.get('reasoning_effort')!r} did not match {expected!r}"
        )


def _validate_profile_policy(profile: dict[str, Any], required_profile: str) -> None:
    """Require a readback that the profile is still the restricted catalog."""

    if profile.get("localToolProfileId") != required_profile:
        raise RustyCrewApiError(
            f"profile policy resolved localToolProfileId={profile.get('localToolProfileId')!r}"
        )
    policy = _dict(profile.get("toolPolicy"))
    requested = policy.get("requestedToolsets")
    if requested != [required_profile]:
        raise RustyCrewApiError(
            f"profile tool policy requested toolsets {requested!r}, not [{required_profile!r}]"
        )
    requested_tools = policy.get("requestedTools")
    if requested_tools != ["deliver_completion_md"]:
        raise RustyCrewApiError(
            "vision_playtester profile requested tools must be exactly "
            f"['deliver_completion_md'], got {requested_tools!r}"
        )
    bindings = profile.get("mcpBindings")
    if isinstance(bindings, list) and bindings:
        raise RustyCrewApiError("vision_playtester profile unexpectedly exposes MCP bindings")


def _safe_identity(run_id: str, scenario_id: str, candidate_id: str, attempt: int = 0) -> str:
    raw = f"{run_id}-{scenario_id}-{candidate_id}-attempt-{attempt}".lower()
    value = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    return value[-100:] or "playtest"


def _cancel_broker_session(candidate: CandidateConfig, session_id: str) -> dict[str, Any]:
    """Best-effort cancellation when a Crew turn dies before playtest_finish."""

    cli_path = str(
        candidate.config.get("playtest_cli")
        or os.environ.get("RUSTY_CREW_PLAYTEST_CLI")
        or "den-playwright"
    )
    config_path = str(
        candidate.config.get("playtest_config")
        or os.environ.get("RUSTY_CREW_PLAYTEST_CONFIG")
        or ""
    )
    if not config_path:
        return {"cancel_requested": False, "cancel_status": "unconfigured", "session_id": session_id}
    request = json.dumps({"annotation": "GoblinBench runner cleanup after interrupted Crew turn"})
    try:
        completed = subprocess.run(
            [cli_path, "playtest", "cancel", session_id, "-config", config_path, "-request", request],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"cancel_requested": True, "cancel_status": "failed", "cancel_error": str(exc), "session_id": session_id}
    return {
        "cancel_requested": True,
        "cancel_status": "completed" if completed.returncode == 0 else "failed",
        "cancel_exit_code": completed.returncode,
        "cancel_error": (completed.stderr or "").strip() or None,
        "session_id": session_id,
    }


def _retryable_infrastructure_error(error: str | None) -> bool:
    if not error:
        return False
    value = error.casefold()
    if any(marker in value for marker in (
        "target revision mismatch",
        "profile policy",
        "local tool profile",
        "provider alias",
        "resolved model",
        "mutation proof",
        "requires local_tool_profile",
        "expected_revision",
    )):
        return False
    return any(marker in value for marker in (
        "timed out",
        "timeout",
        "request failed",
        "http 429",
        "http 502",
        "http 503",
        "http 504",
        "wake dispatch",
        "provider request",
        "connection reset",
        "temporarily unavailable",
    ))
