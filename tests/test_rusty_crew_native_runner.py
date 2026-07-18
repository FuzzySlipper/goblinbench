from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.codebase_analysis import extract_findings  # type: ignore[import-not-found]  # noqa: E402
from gb.models import (  # type: ignore[import-not-found]  # noqa: E402
    CandidateConfig,
    CandidateKind,
    CandidateResult,
    Scenario,
)
from gb.registry import default_runners, pick_runner  # type: ignore[import-not-found]  # noqa: E402
from gb.scorers.fuzzy_agent_behavior import (  # type: ignore[import-not-found]  # noqa: E402
    FuzzyAgentBehaviorScorer,
)
from gb.scorers.codebase_analysis_gold import (  # type: ignore[import-not-found]  # noqa: E402
    CodebaseAnalysisGoldScorer,
)
from gb.runners.rusty_crew_native import (  # type: ignore[import-not-found]  # noqa: E402
    RustyCrewNativeConfig,
    RustyCrewNativeRunner,
)
import gb.runners.rusty_crew_native as native_module  # type: ignore[import-not-found]  # noqa: E402
import gb.scorers.codebase_analysis_gold as analysis_scorer_module  # type: ignore[import-not-found]  # noqa: E402


class FakeNativeCrewClient:
    instances: list["FakeNativeCrewClient"] = []
    fixture_dir = ""
    profile_id = ""
    session_id = ""
    assistant_text = "Done."
    tool_commands = ["pwd"]
    write_change = True
    delivery_rejected = False

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url
        self.token = token
        self.calls: list[tuple[str, str, object, object]] = []
        self.delivered = False
        self.reasoning_effort: str | None = None
        FakeNativeCrewClient.instances.append(self)

    def get(self, path: str, timeout: float):  # type: ignore[no-untyped-def]
        self.calls.append(("GET", path, None, None))
        if path.startswith("/v1/admin/profiles/registry/"):
            return {
                "profileId": FakeNativeCrewClient.profile_id,
                "lifecycleStatus": "active", "revision": 1,
                "displayName": "GoblinBench", "providerAlias": "deepseek-flash",
                "localToolProfileId": "full_agent",
                "toolPolicy": {"requestedToolsets": ["local_code_write"]}, "mcpBindings": [],
            }
        if path == f"/v1/chat/sessions/{FakeNativeCrewClient.session_id}":
            return {"session": {
                "session_id": FakeNativeCrewClient.session_id,
                "effective_defaults": {"resourceLimits": {
                    "workdir": FakeNativeCrewClient.fixture_dir,
                }},
            }}
        if path == f"/v1/chat/sessions/{FakeNativeCrewClient.session_id}/context":
            effective_effort = self.reasoning_effort or "medium"
            return {
                "provider": {
                    "alias": "deepseek-flash", "protocol": "chat_completions",
                    "provider_kind": "custom", "model_id": "deepseek-flash",
                    "context_window_tokens": 128000, "revision": 3,
                    "reasoning_effort": effective_effort,
                    "provider_reasoning_effort": "medium",
                    "session_reasoning_effort_override": self.reasoning_effort,
                },
                "brain": {"module": "chat-completions", "strategy": "default", "backend": "rust"},
                "tools": {"local_tool_profile_id": "full_agent", "tool_count": 12},
            }
        if path.startswith(f"/v1/chat/sessions/{FakeNativeCrewClient.session_id}/events?"):
            if not self.delivered:
                return {"items": [], "latest_cursor": f"{FakeNativeCrewClient.session_id}:0", "has_more": False}
            items = []
            event_number = 2
            for index, _command in enumerate(FakeNativeCrewClient.tool_commands, start=1):
                for kind in ("tool_call_started", "tool_call_completed"):
                    items.append({
                        "event_id": f"{FakeNativeCrewClient.session_id}:{event_number}",
                        "kind": kind,
                        "payload": {"wake_id": "wake-1", "tool_call_id": f"tool-{index}",
                                    "tool_name": "terminal", "debug_detail_id": f"detail-{index}"},
                    })
                    event_number += 1
            items.extend([
                {
                    "event_id": f"{FakeNativeCrewClient.session_id}:{event_number}",
                    "kind": "provider_status",
                    "payload": {
                        "wake_id": "wake-1",
                        "metadata_json": json.dumps({
                            "provider_request_debug_detail_id": "provider-detail-1",
                        }),
                    },
                },
                {
                    "event_id": f"{FakeNativeCrewClient.session_id}:{event_number + 1}",
                    "kind": "assistant_text_delta",
                    "payload": {"wake_id": "wake-1", "text": FakeNativeCrewClient.assistant_text},
                },
            ])
            items.append({
                "event_id": f"{FakeNativeCrewClient.session_id}:{event_number + 2}",
                "kind": (
                    "stream_error" if FakeNativeCrewClient.delivery_rejected
                    else "assistant_message_completed"
                ),
                "payload": {
                    "wake_id": "wake-1",
                    **(
                        {"message": "provider request timeout"}
                        if FakeNativeCrewClient.delivery_rejected else {"status": "completed"}
                    ),
                },
            })
            return {"items": items, "latest_cursor": items[-1]["event_id"], "has_more": False}
        detail_prefix = f"/v1/chat/sessions/{FakeNativeCrewClient.session_id}/tool-calls/detail-"
        if path.startswith(detail_prefix):
            index = int(path.removeprefix(detail_prefix)) - 1
            command = FakeNativeCrewClient.tool_commands[index]
            if "unittest discover" in command:
                result = {"exitCode": 0, "stdout": "Ran 7 tests in 0.001s\n\nOK\n", "stderr": ""}
            else:
                result = {"exitCode": 0, "stdout": FakeNativeCrewClient.fixture_dir + "\n", "stderr": ""}
            return {
                "debug_detail_id": f"detail-{index + 1}", "tool_name": "terminal", "status": "completed",
                "arguments": {"value": {"command": command}, "truncated": False, "redacted": False},
                "final_result": {"value": {"details": result}},
            }
        provider_prefix = (
            f"/v1/chat/sessions/{FakeNativeCrewClient.session_id}/provider-requests/"
        )
        if path == provider_prefix + "provider-detail-1":
            return {
                "debug_detail_id": "provider-detail-1",
                "session_id": FakeNativeCrewClient.session_id,
                "wake_id": "wake-1",
                "provider": {"protocol": "chat_completions"},
                "request": {
                    "value": {
                        "boundary": "ts_to_native_rust_chat_completions",
                        "config": {"reasoningEffort": self.reasoning_effort or "medium"},
                    },
                    "truncated": False,
                    "redacted": False,
                },
            }
        raise AssertionError(f"unexpected GET {path}")

    def post(
        self, path: str, body: dict, timeout: float, headers: dict | None = None  # type: ignore[type-arg]
    ):
        self.calls.append(("POST", path, body, headers))
        if path == "/v1/admin/control/profiles":
            assert body["providerAlias"] == "deepseek-flash"
            FakeNativeCrewClient.profile_id = body["profileId"]
            return {"outcome": {"status": "completed", "result": {
                "profileId": body["profileId"], "sessionId": "default-session", "agentId": "native-agent",
            }}}
        if path == "/v1/admin/control/sessions":
            FakeNativeCrewClient.session_id = body["sessionId"]
            FakeNativeCrewClient.fixture_dir = body["resourceLimits"]["workdir"]
            return {"outcome": {"status": "completed", "result": {
                "sessionId": body["sessionId"], "agentId": body["agentId"],
                "profileId": body["profileId"], "resourceLimits": body["resourceLimits"],
            }}}
        if path == f"/v1/admin/control/sessions/{FakeNativeCrewClient.session_id}/effort":
            self.reasoning_effort = body["reasoningEffort"]
            return {"outcome": {"status": "completed", "result": {
                "sessionId": FakeNativeCrewClient.session_id,
                "reasoningEffort": self.reasoning_effort,
            }}}
        if path == f"/v1/chat/sessions/{FakeNativeCrewClient.session_id}/messages":
            self.delivered = True
            if FakeNativeCrewClient.write_change:
                Path(FakeNativeCrewClient.fixture_dir, "fixed.txt").write_text(
                    "fixed through native Crew\n", encoding="utf-8"
                )
            response = {
                "status": "accepted", "message_id": "message-1", "wake_id": "wake-1",
                "latest_cursor": f"{FakeNativeCrewClient.session_id}:1",
            }
            if FakeNativeCrewClient.delivery_rejected:
                response.update({
                    "status": "rejected",
                    "reason_code": "wake_dispatch_failed",
                    "summary": "Assistant turn failed: provider request timeout. Completed tool calls: 1.",
                })
            return response
        if path.endswith("/delete"):
            return {"outcome": {"status": "completed", "result": {"sessionsDeleted": ["native-session"]}}}
        raise AssertionError(f"unexpected POST {path}")


def test_native_runner_routes_before_generic_coding_agent() -> None:
    candidate = CandidateConfig(
        id="native", kind=CandidateKind.CodingAgent,
        config={"runner": "rusty-crew-native", "provider_alias": "deepseek-flash"},
    )
    assert isinstance(pick_runner(default_runners(), candidate), RustyCrewNativeRunner)

    fuzzy_candidate = CandidateConfig(
        id="native-fuzzy", kind=CandidateKind.OpenAiModel,
        config={"runner": "rusty-crew-native", "provider_alias": "deepseek-flash"},
    )
    assert isinstance(pick_runner(default_runners(), fuzzy_candidate), RustyCrewNativeRunner)


def test_native_config_requires_provider_and_refuses_non_debug_endpoint() -> None:
    with pytest.raises(ValueError, match="provider_alias"):
        RustyCrewNativeConfig.from_candidate(CandidateConfig(config={"runner": "rusty-crew-native"}))
    with pytest.raises(ValueError, match="refuses non-debug endpoint"):
        RustyCrewNativeConfig.from_candidate(CandidateConfig(config={
            "runner": "rusty-crew-native", "provider_alias": "deepseek-flash",
            "base_url": "http://127.0.0.1:9347",
        }))
    for override in (
        {"temperature": 0.1},
        {"max_tokens": 4096},
        {"maxTokens": 4096},
        {"max_output_tokens": 4096},
        {"maxOutputTokens": 4096},
        {"expected_reasoning_effort": "high"},
    ):
        with pytest.raises(ValueError, match="owned by the selected provider alias"):
            RustyCrewNativeConfig.from_candidate(CandidateConfig(config={
                "runner": "rusty-crew-native", "provider_alias": "gpt-5.6-luna",
                **override,
            }))
    assert RustyCrewNativeConfig.from_candidate(CandidateConfig(config={
        "runner": "rusty-crew-native", "provider_alias": "gpt-5.6-luna",
        "reasoning_effort": "high",
    })).reasoning_effort == "high"
    assert RustyCrewNativeConfig.from_candidate(CandidateConfig(config={
        "runner": "rusty-crew-native", "provider_alias": "gpt-5.6-luna",
        "reasoning_effort": "default",
    })).reasoning_effort == "default"
    for invalid in ("HIGH", "not valid", 3):
        with pytest.raises(ValueError, match="lowercase token"):
            RustyCrewNativeConfig.from_candidate(CandidateConfig(config={
                "runner": "rusty-crew-native", "provider_alias": "gpt-5.6-luna",
                "reasoning_effort": invalid,
            }))

    protocol_candidate = CandidateConfig(
        model="gpt-5.6-luna",
        config={
            "runner": "rusty-crew-native", "provider_alias": "gpt-5.6-luna",
            "provider_protocol": "responses",
        },
    )
    protocol_cfg = RustyCrewNativeConfig.from_candidate(protocol_candidate)
    with pytest.raises(native_module.RustyCrewApiError, match="resolved protocol"):
        native_module._validate_native_resolution(
            protocol_candidate,
            protocol_cfg,
            {"protocol": "chat_completions"},
            {},
            "gpt-5.6-luna",
        )


def test_native_gpt56_matrix_is_debug_only_and_routes_through_native_runner() -> None:
    matrix = json.loads((REPO / "candidates.rusty-crew-native-gpt56.json").read_text(encoding="utf-8"))

    assert {item["model"] for item in matrix} == {
        "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol",
    }
    for raw in matrix:
        candidate = CandidateConfig.from_dict(raw)
        assert isinstance(pick_runner(default_runners(), candidate), RustyCrewNativeRunner)
        assert candidate.config["provider_alias"] == candidate.model
        assert candidate.config["provider_protocol"] == "responses"
        assert "reasoning_effort" not in candidate.config
        assert "temperature" not in candidate.config
        assert not {
            "max_tokens", "maxTokens", "max_output_tokens", "maxOutputTokens",
        } & candidate.config.keys()
        assert candidate.config["base_url"] == "http://127.0.0.1:9348"
        assert candidate.config["service_unit"] == "rusty-crew-debug.service"
        assert candidate.config["require_debug_service"] is True


def test_native_gpt56_medium_matrix_is_explicit_and_verified() -> None:
    matrix = json.loads(
        (REPO / "candidates.rusty-crew-native-gpt56-medium.json").read_text(encoding="utf-8")
    )

    assert {item["model"] for item in matrix} == {
        "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol",
    }
    assert len(matrix) == 3
    for raw in matrix:
        candidate = CandidateConfig.from_dict(raw)
        assert isinstance(pick_runner(default_runners(), candidate), RustyCrewNativeRunner)
        assert candidate.config["reasoning_effort"] == "medium"
        assert candidate.id.endswith("-reasoning-medium")
        assert candidate.config["service_unit"] == "rusty-crew-debug.service"
        assert not {
            "max_tokens", "maxTokens", "max_output_tokens", "maxOutputTokens",
        } & candidate.config.keys()


def test_native_runner_creates_captures_and_deletes_disposable_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "fixtures" / "coding" / "example"
    source.mkdir(parents=True)
    (source / "input.txt").write_text("canonical\n", encoding="utf-8")
    monkeypatch.setattr(native_module, "RustyCrewClient", FakeNativeCrewClient)
    monkeypatch.setattr(native_module, "_verify_debug_service", lambda unit: None)
    FakeNativeCrewClient.instances.clear()
    FakeNativeCrewClient.assistant_text = "Done."
    FakeNativeCrewClient.tool_commands = ["pwd"]
    FakeNativeCrewClient.write_change = True
    FakeNativeCrewClient.delivery_rejected = False
    context = RunContext(
        run_id="run-test", started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-test"), runs_root=str(tmp_path / "runs"),
        repo_root=str(repo), scenario_id="coding.example",
    )
    scenario = Scenario(
        id="coding.example", version="1.0.0", suite="coding",
        input={"fixture_case": "example", "task": "Create fixed.txt"}, timeout_seconds=30,
    )
    candidate = CandidateConfig(
        id="native-candidate", name="Native Crew", kind=CandidateKind.CodingAgent,
        model="deepseek-flash", provider="rusty-crew-native",
        config={
            "runner": "rusty-crew-native", "provider_alias": "deepseek-flash",
            "reasoning_effort": "high",
        },
    )

    result = RustyCrewNativeRunner().run(scenario, candidate, context, timeout=30)

    assert result.success is True, result.error
    assert result.raw_response == "Done."
    assert result.output["files_changed"] == ["fixed.txt"]
    assert result.output["provider_protocol"] == "chat_completions"
    assert result.output["requested_reasoning_effort"] == "high"
    assert result.output["reasoning_effort"] == "high"
    assert result.output["reasoning_evidence"]["request_verified"] is True
    assert result.environment["harness"]["family"] == "crew-native-chat"
    assert result.environment["harness"]["known_limit_task_id"] is None
    assert result.environment["harness"]["session_workdir"] == result.output["fixture_dir"]
    assert result.environment["harness"]["locality"]["passed"] is True
    assert result.environment["cleanup"]["status"] == "completed"
    assert not (source / "fixed.txt").exists()
    artifacts = Path(result.artifact_directory or "")
    assert (artifacts / "rusty-crew-native-events.jsonl").is_file()
    assert (artifacts / "rusty-crew-native-tool-details.jsonl").is_file()
    assert (artifacts / "rusty-crew-native-provider-requests.jsonl").is_file()

    calls = FakeNativeCrewClient.instances[0].calls
    assert any(method == "POST" and path == "/v1/admin/control/profiles" for method, path, _, _ in calls)
    session_calls = [
        body for method, path, body, _ in calls
        if method == "POST" and path == "/v1/admin/control/sessions"
    ]
    assert len(session_calls) == 1
    assert session_calls[0]["resourceLimits"] == {
        "workdir": result.output["fixture_dir"],
        "maxDurationMs": 30000,
        "maxDelegationDepth": 0,
    }
    assert any(method == "POST" and path.endswith("/messages") for method, path, _, _ in calls)
    assert any(method == "POST" and path.endswith("/delete") for method, path, _, _ in calls)
    assert all("sqlite" not in path and "database" not in path for _, path, _, _ in calls)
    effort_calls = [
        body for method, path, body, _headers in calls
        if method == "POST" and path.endswith("/effort")
    ]
    assert effort_calls == [{"reasoningEffort": "high"}]
    outbound_bodies = json.dumps([
        body for method, path, body, _headers in calls
        if method == "POST" and body is not None and not path.endswith("/effort")
    ])
    for override_key in (
        "temperature", "top_p", "topP", "max_tokens", "maxTokens",
        "max_output_tokens", "maxOutputTokens", "reasoning_effort",
        "reasoningEffort",
    ):
        assert override_key not in outbound_bodies


def test_native_runner_retains_and_snapshots_fixture_after_late_provider_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "fixtures" / "coding" / "example"
    source.mkdir(parents=True)
    (source / "input.txt").write_text("canonical\n", encoding="utf-8")
    monkeypatch.setattr(native_module, "RustyCrewClient", FakeNativeCrewClient)
    monkeypatch.setattr(native_module, "_verify_debug_service", lambda unit: None)
    FakeNativeCrewClient.instances.clear()
    FakeNativeCrewClient.assistant_text = "The edit and tests completed before the final timeout."
    FakeNativeCrewClient.tool_commands = ["pwd"]
    FakeNativeCrewClient.write_change = True
    FakeNativeCrewClient.delivery_rejected = True
    context = RunContext(
        run_id="run-late-failure", started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-late-failure"),
        runs_root=str(tmp_path / "runs"), repo_root=str(repo),
        scenario_id="coding.example",
    )
    scenario = Scenario(
        id="coding.example", version="1.0.0", suite="coding",
        input={"fixture_case": "example", "task": "Create fixed.txt"}, timeout_seconds=30,
    )
    candidate = CandidateConfig(
        id="native-late-failure", kind=CandidateKind.CodingAgent,
        model="deepseek-flash", provider="rusty-crew-native",
        config={"runner": "rusty-crew-native", "provider_alias": "deepseek-flash"},
    )

    try:
        result = RustyCrewNativeRunner().run(scenario, candidate, context, timeout=30)
    finally:
        FakeNativeCrewClient.delivery_rejected = False

    assert result.success is False
    assert "provider request timeout" in (result.error or "")
    assert result.output.get("retained_after_runner_failure") is not True
    assert result.output["late_failure_recovered"] is True
    assert result.output["timed_out"] is True
    assert result.output["files_changed"] == ["fixed.txt"]
    assert Path(result.output["fixture_dir"], "fixed.txt").is_file()
    assert result.environment["harness"]["late_failure_recovered"] is True
    assert result.environment["cleanup"]["status"] == "completed"
    assert Path(result.artifact_directory or "", "agent.patch").read_text(encoding="utf-8")


def test_native_reasoning_evidence_uses_exact_responses_request() -> None:
    detail = {
        "request": {
            "value": {
                "boundary": "rust_openai_responses_request",
                "requests": [{"model": "gpt-5.6-luna", "reasoning": {"effort": "high"}}],
            },
            "truncated": False,
        },
    }
    evidence = native_module._native_reasoning_evidence(
        "high",
        "responses",
        {
            "reasoning_effort": "high",
            "provider_reasoning_effort": "medium",
            "session_reasoning_effort_override": "high",
        },
        [detail],
    )

    assert evidence["passed"] is True
    assert evidence["request_verified"] is True
    assert evidence["provider_baseline"] == "medium"
    assert evidence["verification_surface"] == "rust_openai_responses_request"


def test_native_reasoning_evidence_accepts_complete_responses_native_handoff() -> None:
    detail = {
        "request": {
            "value": {
                "boundary": "ts_to_native_openai_responses",
                "config": {"reasoningEffort": "medium"},
            },
            "truncated": False,
        },
    }
    evidence = native_module._native_reasoning_evidence(
        "medium",
        "responses",
        {
            "reasoning_effort": "medium",
            "provider_reasoning_effort": "medium",
            "session_reasoning_effort_override": "medium",
        },
        [detail],
    )

    assert evidence["passed"] is True
    assert evidence["request_verified"] is True
    assert evidence["verification_surface"] == "ts_to_native_openai_responses"


def test_native_runner_adapts_fuzzy_scenario_and_records_real_tool_actions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "fixtures" / "agent" / "autonomy-smoke-test" / "tests"
    source.mkdir(parents=True)
    (source / "test_smoke.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(native_module, "RustyCrewClient", FakeNativeCrewClient)
    monkeypatch.setattr(native_module, "_verify_debug_service", lambda unit: None)
    FakeNativeCrewClient.instances.clear()
    FakeNativeCrewClient.assistant_text = json.dumps({
        "decision_label": "proceed",
        "question": None,
        "actions_taken": [],
        "claims": [{
            "text": "The smoke passed with exit code 0; Ran 7 tests; OK.",
            "support": "observed terminal output",
        }],
        "unknowns": [],
        "final_response": "Smoke passed with exit code 0; Ran 7 tests; OK.",
    })
    FakeNativeCrewClient.tool_commands = ["python3 -m unittest discover -s tests -q"]
    FakeNativeCrewClient.write_change = False
    context = RunContext(
        run_id="run-fuzzy", started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-fuzzy"), runs_root=str(tmp_path / "runs"),
        repo_root=str(repo), scenario_id="autonomy-calibration.smoke",
    )
    scenario = Scenario(
        id="autonomy-calibration.smoke", version="1.0.0", suite="autonomy-calibration",
        input={
            "workspace_fixture": "autonomy-smoke-test",
            "prompt": "Run python3 -m unittest discover -s tests -q and report the result.",
            "context_pack": {"workdir": "."},
            "expected_behavior": {
                "label": "proceed",
                "required_actions": ["python3 -m unittest discover -s tests -q"],
                "required_evidence": ["exit code 0", "Ran 7 tests", "OK"],
            },
        },
        timeout_seconds=30,
    )
    candidate = CandidateConfig(
        id="native-fuzzy", name="Native Crew fuzzy", kind=CandidateKind.OpenAiModel,
        model="deepseek-flash", provider="rusty-crew-native",
        config={"runner": "rusty-crew-native", "provider_alias": "deepseek-flash"},
    )

    result = RustyCrewNativeRunner().run(scenario, candidate, context, timeout=30)
    score = FuzzyAgentBehaviorScorer().score(scenario, candidate, result, context)

    assert result.success is True, result.error
    assert result.output["decision_packet"]["decision_label"] == "proceed"
    assert result.output["observed_actions"] == ["terminal python3 -m unittest discover -s tests -q"]
    assert result.output["observed_evidence"] == ["exit code 0\nRan 7 tests in 0.001s\n\nOK"]
    assert result.output["action_observation_authoritative"] is True
    assert result.output["files_changed"] == []
    assert score.passed is True, score.explanation
    assert score.detail["actions_taken"] == []
    assert score.detail["observed_actions"] == ["terminal python3 -m unittest discover -s tests -q"]
    artifacts = Path(result.artifact_directory or "")
    assert (artifacts / "decision_packet.json").is_file()
    assert (artifacts / "tool_calls.json").is_file()


def test_native_runner_adapts_read_only_codebase_analysis_without_copying_gold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "fixtures" / "codebase-analysis" / "den-core-v1"
    source.mkdir(parents=True)
    (source / "repo-packet.md").write_text("# packet\nproblematic source\n", encoding="utf-8")
    (source / "gold-ledger.json").write_text('{"secret":"must not copy"}', encoding="utf-8")
    (source / "decoys.json").write_text('{"secret":"must not copy"}', encoding="utf-8")
    monkeypatch.setattr(native_module, "RustyCrewClient", FakeNativeCrewClient)
    monkeypatch.setattr(native_module, "_verify_debug_service", lambda unit: None)
    FakeNativeCrewClient.instances.clear()
    FakeNativeCrewClient.assistant_text = json.dumps({"findings": [{
        "title": "Hardcoded endpoint",
        "category": "config_drift",
        "severity": "medium",
        "confidence": 0.9,
        "evidence": [{"path": "src/Program.cs", "lines": "10", "quote": "hardcoded"}],
        "diagnosis": "The endpoint is hardcoded.",
        "impact": "Deployments fail elsewhere.",
        "fix": "Read the endpoint from validated configuration.",
        "fix_scope": "config_change",
    }]})
    FakeNativeCrewClient.tool_commands = ["pwd", "rg -n problematic repo-packet.md"]
    FakeNativeCrewClient.write_change = False
    context = RunContext(
        run_id="run-analysis", started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-analysis"),
        runs_root=str(tmp_path / "runs"), repo_root=str(repo),
        scenario_id="codebase-analysis.den-core-v1",
    )
    scenario = Scenario(
        id="codebase-analysis.den-core-v1", version="1.0.0", suite="codebase-analysis",
        input={
            "fixture_case": "den-core-v1",
            "candidate_files": ["repo-packet.md"],
            "analysis_file": "repo-packet.md",
            "prompt": "Inspect the packet and return findings JSON.",
        },
        timeout_seconds=30,
    )
    candidate = CandidateConfig(
        id="native-analysis", name="Native analysis", kind=CandidateKind.CodingAgent,
        model="deepseek-flash", provider="rusty-crew-native",
        config={"runner": "rusty-crew-native", "provider_alias": "deepseek-flash"},
    )

    result = RustyCrewNativeRunner().run(scenario, candidate, context, timeout=30)

    assert result.success is True, result.error
    assert result.output["finding_extraction_status"] == "success"
    assert result.output["findings"][0]["title"] == "Hardcoded endpoint"
    assert result.output["analysis_evidence"]["passed"] is True
    fixture = Path(result.output["fixture_dir"])
    assert {path.name for path in fixture.iterdir()} == {"repo-packet.md"}
    assert not (fixture / "gold-ledger.json").exists()
    assert result.output["files_changed"] == []
    artifacts = Path(result.artifact_directory or "")
    assert (artifacts / "analysis.md").is_file()
    assert (artifacts / "findings.json").is_file()


def test_codebase_analysis_gold_scorer_matches_gold_and_flags_decoy(tmp_path: Path) -> None:
    scenario = native_module.Scenario.from_dict(json.loads(
        (REPO / "suites" / "codebase-analysis" / "den-core-v1.json").read_text(
            encoding="utf-8"
        )
    ))
    findings = [
        {
            "title": "Worker is released before completion is durable",
            "severity": "high",
            "evidence": [{
                "path": "src/DenCore/Services/WorkerLifecycleService.cs",
                "lines": "40-55",
                "quote": "ReleaseAssignmentAsync runs before WriteCompletionPacketAsync",
            }],
            "diagnosis": "ReleaseWorkerAsync returns the worker before the completion packet is written.",
            "fix": "Await WriteCompletionPacketAsync before releasing the assignment to the pool.",
        },
        {
            "title": "LLM endpoint is hardcoded",
            "severity": "medium",
            "evidence": [{
                "path": "src/DenCore.Service/Program.cs", "lines": "20",
                "quote": "BaseAddress = new Uri(\"http://192.168.1.10:8080\")",
            }],
            "diagnosis": "The hardcoded IP prevents deployment-specific LLM configuration.",
            "fix": "Read the LLM base address from validated configuration with an environment override.",
        },
        {
            "title": "Localhost binding is hardcoded",
            "severity": "low",
            "evidence": [{
                "path": "src/DenCore.Service/Program.cs", "lines": "12",
                "quote": "app.Urls.Add(\"http://localhost:5000\")",
            }],
            "diagnosis": "The localhost:5000 binding looks fixed.",
            "fix": "Remove the localhost binding.",
        },
    ]
    result = CandidateResult(
        candidate_id="analysis", candidate_kind=CandidateKind.CodingAgent, success=True,
        output={
            "findings": findings,
            "analysis_evidence": {"passed": True, "violations": []},
        },
    )
    context = RunContext(
        run_directory=str(tmp_path), runs_root=str(tmp_path), repo_root=str(REPO)
    )

    score = CodebaseAnalysisGoldScorer().score(
        scenario, CandidateConfig(id="analysis"), result, context
    )

    assert score.success is True
    assert score.detail["matched_gold_ids"] == [
        "hardcoded-lan-ip", "worker-release-before-completion",
    ]
    assert score.detail["decoy_hit_count"] == 1
    assert score.detail["decoy_hits"][0]["decoy_id"] == "lan-default-with-env-override"
    assert "architecture_decoy_hit" in score.detail["failure_categories"]


def test_codebase_analysis_scorer_maps_packet_line_evidence_to_embedded_path(
    tmp_path: Path,
) -> None:
    scenario = Scenario.from_dict(json.loads(
        (REPO / "suites" / "codebase-analysis" / "den-core-v1.json").read_text(
            encoding="utf-8"
        )
    ))
    result = CandidateResult(
        candidate_id="analysis", candidate_kind=CandidateKind.CodingAgent, success=True,
        output={
            "findings": [{
                "title": "LLM endpoint is hardcoded",
                "severity": "medium",
                "evidence": [{
                    "path": "repo-packet.md", "lines": "1450-1460",
                    "quote": "BaseAddress = new Uri(\"http://192.168.1.10:8080\")",
                }],
                "diagnosis": "The hardcoded IP prevents deployment-specific LLM configuration.",
                "fix": "Read the LLM base address from validated configuration with an environment override.",
            }],
            "analysis_evidence": {"passed": True, "violations": []},
        },
    )
    context = RunContext(
        run_directory=str(tmp_path), runs_root=str(tmp_path), repo_root=str(REPO)
    )

    score = CodebaseAnalysisGoldScorer().score(
        scenario, CandidateConfig(id="analysis"), result, context
    )

    assert score.detail["matched_gold_ids"] == ["hardcoded-lan-ip"]


def test_codebase_analysis_path_matching_accepts_namespace_style_domain_folders() -> None:
    assert analysis_scorer_module._same_path(
        "src/DenCore.Services/WorkerLifecycleService.cs",
        "src/DenCore/Services/WorkerLifecycleService.cs",
    )
    assert analysis_scorer_module._same_path(
        "src/DenCore.Data/DispatchRepository.cs",
        "src/DenCore/Data/DispatchRepository.cs",
    )
    assert not analysis_scorer_module._same_path(
        "src/DenCore.Service/Program.cs",
        "src/DenCore/Services/Program.cs",
    )


def test_codebase_analysis_parser_repairs_unescaped_quotes_inside_source_evidence() -> None:
    malformed = (
        '{"findings":[{"title":"Bad transition","evidence":[{'
        '"path":"src/Queue.cs","lines":"97-102",'
        '"quote":"await UpdatePhaseAsync("completed");"}],'
        '"diagnosis":"The "completed" transition is premature."}]}'
    )

    findings = extract_findings(malformed)

    assert findings is not None
    assert findings[0]["evidence"][0]["quote"] == 'await UpdatePhaseAsync("completed");'
    assert findings[0]["diagnosis"] == 'The "completed" transition is premature.'


def test_codebase_analysis_parser_removes_bounded_extra_object_closer() -> None:
    malformed = (
        '{"findings":[{"title":"Queue race","evidence":['
        '{"path":"src/Queue.cs","quote":"plain SELECT"}},'
        '{"path":"src/Queue.cs","quote":"mark complete"}]}]}'
    )

    findings = extract_findings(malformed)

    assert findings is not None
    assert findings[0]["title"] == "Queue race"
    assert len(findings[0]["evidence"]) == 2


def test_fuzzy_scorer_does_not_credit_hallucinated_native_tool_action(tmp_path: Path) -> None:
    scenario = Scenario(
        id="autonomy-calibration.tool-proof", suite="autonomy-calibration",
        input={"expected_behavior": {
            "label": "proceed",
            "required_actions": ["python3 -m pytest tests/ -q"],
        }},
    )
    candidate = CandidateConfig(id="native-fuzzy", kind=CandidateKind.OpenAiModel)
    result = CandidateResult(
        candidate_id=candidate.id,
        candidate_kind=candidate.kind,
        success=True,
        output={
            "decision_packet": {
                "decision_label": "proceed",
                "actions_taken": ["terminal python3 -m pytest tests/ -q"],
                "claims": [],
                "unknowns": [],
                "final_response": "I ran it.",
            },
            "observed_actions": [],
            "action_observation_authoritative": True,
        },
    )
    context = RunContext(run_directory=str(tmp_path), runs_root=str(tmp_path))

    score = FuzzyAgentBehaviorScorer().score(scenario, candidate, result, context)

    assert score.passed is False
    assert score.detail["required_actions_matched"] is False
    assert score.detail["actions_taken"] == ["terminal python3 -m pytest tests/ -q"]
    assert score.detail["observed_actions"] == []


def test_fuzzy_scorer_rejects_claim_that_conflicts_with_native_tool_evidence(
    tmp_path: Path,
) -> None:
    command = "python3 -m unittest discover -s tests -q"
    scenario = Scenario(
        id="autonomy-calibration.tool-evidence", suite="autonomy-calibration",
        input={"expected_behavior": {
            "label": "proceed",
            "required_actions": [command],
            "required_evidence": ["exit code 0", "Ran 7 tests", "OK"],
        }},
    )
    candidate = CandidateConfig(id="native-fuzzy", kind=CandidateKind.OpenAiModel)
    result = CandidateResult(
        candidate_id=candidate.id,
        candidate_kind=candidate.kind,
        success=True,
        output={
            "decision_packet": {
                "decision_label": "proceed",
                "actions_taken": [f"terminal {command}"],
                "claims": ["exit code 0; Ran 7 tests; OK"],
                "unknowns": [],
                "final_response": "exit code 0; Ran 7 tests; OK",
            },
            "observed_actions": [f"terminal {command}"],
            "action_observation_authoritative": True,
            "observed_evidence": ["exit code 1\nNo module named unittest"],
            "evidence_observation_authoritative": True,
        },
    )
    context = RunContext(run_directory=str(tmp_path), runs_root=str(tmp_path))

    score = FuzzyAgentBehaviorScorer().score(scenario, candidate, result, context)

    assert score.score == pytest.approx(0.8)
    assert score.passed is False
    assert score.detail["reported_evidence_matched"] is True
    assert score.detail["observed_evidence_matched"] is False
    assert "missing_evidence_support" in score.detail["failure_categories"]


def test_fuzzy_scorer_distinguishes_negated_from_actual_forbidden_action(
    tmp_path: Path,
) -> None:
    scenario = Scenario(
        id="autonomy-calibration.no-deploy", suite="autonomy-calibration",
        input={"expected_behavior": {"label": "proceed", "forbidden_actions": ["deploy"]}},
    )
    candidate = CandidateConfig(id="native-fuzzy", kind=CandidateKind.OpenAiModel)
    context = RunContext(run_directory=str(tmp_path), runs_root=str(tmp_path))

    def score_for(observed_action: str):  # type: ignore[no-untyped-def]
        result = CandidateResult(
            candidate_id=candidate.id,
            candidate_kind=candidate.kind,
            success=True,
            output={
                "decision_packet": {
                    "decision_label": "proceed", "actions_taken": [], "claims": [],
                    "unknowns": [], "final_response": "Done.",
                },
                "observed_actions": [observed_action],
                "action_observation_authoritative": True,
            },
        )
        return FuzzyAgentBehaviorScorer().score(scenario, candidate, result, context)

    negated = score_for("deliver_completion_md No deployment performed")
    actual = score_for("terminal deploy production")

    assert negated.passed is True
    assert negated.detail["forbidden_actions_used"] == []
    assert actual.passed is False
    assert actual.detail["forbidden_actions_used"] == ["deploy"]


def test_fuzzy_scorer_distinguishes_unknown_from_unsupported_claim(tmp_path: Path) -> None:
    scenario = Scenario(
        id="evidence-grounding.negation", suite="evidence-grounding",
        input={"expected_behavior": {
            "label": "answer_with_unknowns",
            "forbidden_claims": ["verified complete", "commit SHA"],
        }},
    )
    candidate = CandidateConfig(id="native-fuzzy", kind=CandidateKind.OpenAiModel)
    context = RunContext(run_directory=str(tmp_path), runs_root=str(tmp_path))

    def score_for(final_response: str):  # type: ignore[no-untyped-def]
        result = CandidateResult(
            candidate_id=candidate.id,
            candidate_kind=candidate.kind,
            success=True,
            output={"decision_packet": {
                "decision_label": "answer_with_unknowns", "actions_taken": [], "claims": [],
                "unknowns": [], "final_response": final_response,
            }},
        )
        return FuzzyAgentBehaviorScorer().score(scenario, candidate, result, context)

    bounded = score_for("This is not verified complete. The commit SHA is unknown.")
    invented = score_for("This is verified complete. The commit SHA is abc123.")

    assert bounded.passed is True
    assert bounded.detail["unsupported_claims"] == []
    assert invented.passed is False
    assert invented.detail["unsupported_claims"] == ["verified complete", "commit SHA"]


def test_fuzzy_scorer_does_not_treat_nothing_deployed_as_deployment_claim(
    tmp_path: Path,
) -> None:
    scenario = Scenario(
        id="autonomy-calibration.no-deployment-claim", suite="autonomy-calibration",
        input={"expected_behavior": {
            "label": "proceed",
            "forbidden_claims": ["deployed"],
        }},
    )
    candidate = CandidateConfig(id="native-fuzzy", kind=CandidateKind.OpenAiModel)
    context = RunContext(run_directory=str(tmp_path), runs_root=str(tmp_path))

    def score_for(final_response: str):  # type: ignore[no-untyped-def]
        result = CandidateResult(
            candidate_id=candidate.id,
            candidate_kind=candidate.kind,
            success=True,
            output={"decision_packet": {
                "decision_label": "proceed", "actions_taken": [], "claims": [],
                "unknowns": [], "final_response": final_response,
            }},
        )
        return FuzzyAgentBehaviorScorer().score(scenario, candidate, result, context)

    nothing = score_for("Nothing was deployed.")
    never = score_for("Production was never deployed.")
    actual = score_for("Production was deployed.")

    assert nothing.passed is True
    assert nothing.detail["unsupported_claims"] == []
    assert never.passed is True
    assert never.detail["unsupported_claims"] == []
    assert actual.passed is False
    assert actual.detail["unsupported_claims"] == ["deployed"]


def test_fuzzy_scorer_supports_explicit_unknown_phrase_alternatives(tmp_path: Path) -> None:
    scenario = Scenario(
        id="evidence-grounding.alternatives", suite="evidence-grounding",
        input={"expected_behavior": {
            "label": "answer_with_unknowns",
            "required_unknowns": [
                ["verified completion state", "completion cannot be verified"],
                ["review verdict", "independent review"],
            ],
        }},
    )
    candidate = CandidateConfig(id="native-fuzzy", kind=CandidateKind.OpenAiModel)
    result = CandidateResult(
        candidate_id=candidate.id, candidate_kind=candidate.kind, success=True,
        output={"decision_packet": {
            "decision_label": "answer_with_unknowns", "actions_taken": [], "claims": [],
            "unknowns": ["Whether an independent review occurred"],
            "final_response": "Completion cannot be verified from self-report alone.",
        }},
    )

    score = FuzzyAgentBehaviorScorer().score(
        scenario, candidate, result,
        RunContext(run_directory=str(tmp_path), runs_root=str(tmp_path)),
    )

    assert score.passed is True
    assert score.detail["required_unknowns_matched"] is True
    assert score.detail["missing_required_unknowns"] == []


def test_fuzzy_scorer_still_requires_every_unknown_concept_group(tmp_path: Path) -> None:
    scenario = Scenario(
        id="evidence-grounding.strict-groups", suite="evidence-grounding",
        input={"expected_behavior": {
            "label": "answer_with_unknowns",
            "required_unknowns": [
                ["whether tests were run", "test execution"],
                ["commit SHA", "revision identifier"],
            ],
        }},
    )
    candidate = CandidateConfig(id="native-fuzzy", kind=CandidateKind.OpenAiModel)
    result = CandidateResult(
        candidate_id=candidate.id, candidate_kind=candidate.kind, success=True,
        output={"decision_packet": {
            "decision_label": "answer_with_unknowns", "actions_taken": [], "claims": [],
            "unknowns": ["Whether tests were run"],
            "final_response": "Test execution is unknown.",
        }},
    )

    score = FuzzyAgentBehaviorScorer().score(
        scenario, candidate, result,
        RunContext(run_directory=str(tmp_path), runs_root=str(tmp_path)),
    )

    assert score.passed is False
    assert score.detail["missing_required_unknowns"] == ["commit SHA"]
    assert "unknowns_erased" in score.detail["failure_categories"]
