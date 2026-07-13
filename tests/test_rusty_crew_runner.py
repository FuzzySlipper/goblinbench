from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.models import CandidateConfig, CandidateKind, Scenario  # type: ignore[import-not-found]  # noqa: E402
from gb.registry import default_runners, pick_runner  # type: ignore[import-not-found]  # noqa: E402
from gb.runners.rusty_crew import RustyCrewConfig, RustyCrewRunner  # type: ignore[import-not-found]  # noqa: E402
import gb.runners.rusty_crew as crew_module  # type: ignore[import-not-found]  # noqa: E402


class FakeCrewClient:
    instances: list["FakeCrewClient"] = []
    fixture_dir = ""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url
        self.token = token
        self.delivered = False
        self.calls: list[tuple[str, str, object]] = []
        FakeCrewClient.instances.append(self)

    def get(self, path: str, timeout: float):  # type: ignore[no-untyped-def]
        self.calls.append(("GET", path, None))
        if path == "/v1/external-runtimes":
            return {
                "runtimes": [{
                    "runtimeId": "debug-runtime", "observedState": "ready", "revision": 4,
                    "expectedCliVersion": "0.144.1", "executableSha256": "exe", "protocolSchemaSha256": "schema",
                }],
                "controllers": [{"runtimeId": "debug-runtime", "driverState": "ready"}],
            }
        if path.startswith("/v1/admin/profiles/registry"):
            return {"items": [{
                "profileId": "tester", "lifecycleStatus": "active", "revision": 2,
                "displayName": "Tester", "providerAlias": "gpt", "localToolProfileId": "full_agent",
                "toolPolicy": {"requestedToolsets": ["local_code_write"]}, "mcpBindings": [],
            }]}
        if path.endswith("/commands"):
            return {
                "settings": {"model": "gpt-5.6-terra", "modelProvider": "openai", "effort": "medium"},
                "models": [{
                    "id": "gpt-5.6-terra", "model": "gpt-5.6-terra",
                    "supportedEfforts": [{"value": "medium"}],
                }],
            }
        if "/events?" in path:
            if not self.delivered:
                return {"events": []}
            return {"events": [
                {
                    "eventId": "pwd", "runtimeId": "debug-runtime", "sequenceId": 1,
                    "kind": "command_activity", "nativeThreadId": "thread-1", "nativeTurnId": "turn-1",
                    "itemId": "command-1", "payload": {
                        "nativeMethod": "item/completed", "command": "/bin/bash -lc pwd",
                        "cwd": FakeCrewClient.fixture_dir, "output": FakeCrewClient.fixture_dir + "\n",
                        "status": "completed",
                    },
                },
                {
                    "eventId": "delta", "runtimeId": "debug-runtime", "sequenceId": 2,
                    "kind": "assistant_text_delta", "nativeThreadId": "thread-1", "nativeTurnId": "turn-1",
                    "payload": {"nativeMethod": "item/agentMessage/delta", "text": "Done."},
                },
                {
                    "eventId": "usage", "runtimeId": "debug-runtime", "sequenceId": 3,
                    "kind": "usage", "nativeThreadId": "thread-1", "nativeTurnId": "turn-1",
                    "payload": {"nativeMethod": "thread/tokenUsage/updated", "usage": {
                        "total": {"inputTokens": 100, "cachedInputTokens": 20, "outputTokens": 8,
                                  "reasoningOutputTokens": 2, "totalTokens": 108},
                        "modelContextWindow": 200000,
                    }},
                },
                {
                    "eventId": "terminal", "runtimeId": "debug-runtime", "sequenceId": 4,
                    "kind": "turn_lifecycle", "nativeThreadId": "thread-1", "nativeTurnId": "turn-1",
                    "payload": {"nativeMethod": "turn/completed", "status": "completed"},
                },
            ]}
        if path == "/v1/external-turns/request-1":
            return {"phase": "completed", "nativeThreadId": "thread-1", "nativeTurnId": "turn-1"}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, body: dict, timeout: float):  # type: ignore[no-untyped-def]
        self.calls.append(("POST", path, body))
        if path == "/v1/external-agent-sessions":
            FakeCrewClient.fixture_dir = body["cwd"]
            return {"creation": {
                "phase": "ready", "nativeThreadId": "thread-1",
                "binding": {"bindingId": "binding-1"},
                "session": {"sessionId": "session-1"},
            }}
        if path.endswith("/commands"):
            return {"status": "applied", "result": {}}
        if path.endswith("/messages"):
            self.delivered = True
            Path(FakeCrewClient.fixture_dir, "fixed.txt").write_text("fixed through Crew\n", encoding="utf-8")
            return {"activation": {"type": "external_turn_requested", "requestId": "request-1"}}
        raise AssertionError(f"unexpected POST {path}")


def test_rusty_crew_runner_routes_before_generic_coding_agent() -> None:
    candidate = CandidateConfig(
        id="crew", kind=CandidateKind.CodingAgent,
        config={"runner": "rusty-crew", "runtime_id": "r", "profile_id": "p"},
    )
    assert isinstance(pick_runner(default_runners(), candidate), RustyCrewRunner)


def test_rusty_crew_config_refuses_non_debug_service() -> None:
    candidate = CandidateConfig(
        id="crew", kind=CandidateKind.CodingAgent,
        config={
            "runner": "rusty-crew", "runtime_id": "r", "profile_id": "p",
            "base_url": "http://127.0.0.1:9999",
        },
    )
    with pytest.raises(ValueError, match="refuses non-debug endpoint"):
        RustyCrewConfig.from_candidate(candidate)


def test_debug_service_guard_refuses_production_unit_without_calling_systemctl() -> None:
    with pytest.raises(ValueError, match="rusty-crew-debug.service"):
        crew_module._verify_debug_service("rusty-crew.service")


def test_activity_counts_use_durable_crew_event_vocabulary() -> None:
    events = [
        {"kind": "command_activity", "itemId": "cmd-1"},
        {"kind": "command_activity", "itemId": "cmd-1"},
        {"kind": "file_activity", "itemId": "patch-1"},
        {"kind": "tool_activity", "itemId": "tool-1"},
    ]
    assert crew_module._activity_counts(events) == (1, 2)


def test_rusty_crew_runner_uses_supported_session_surfaces_and_standard_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "fixtures" / "coding" / "example"
    source.mkdir(parents=True)
    (source / "input.txt").write_text("canonical\n", encoding="utf-8")
    monkeypatch.setattr(crew_module, "RustyCrewClient", FakeCrewClient)
    monkeypatch.setattr(crew_module, "_verify_debug_service", lambda unit: None)
    FakeCrewClient.instances.clear()
    context = RunContext(
        run_id="run-test", started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-test"), runs_root=str(tmp_path / "runs"),
        repo_root=str(repo), scenario_id="coding.example",
    )
    scenario = Scenario(
        id="coding.example", version="1.2.3", suite="coding",
        input={"fixture_case": "example", "task": "Create fixed.txt"}, timeout_seconds=30,
    )
    candidate = CandidateConfig(
        id="crew-candidate", name="Crew Test", kind=CandidateKind.CodingAgent,
        model="gpt-5.6-terra", provider="rusty-crew", profile="tester",
        config={
            "runner": "rusty-crew", "runtime_id": "debug-runtime", "profile_id": "tester",
            "reasoning_effort": "medium",
        },
    )

    result = RustyCrewRunner().run(scenario, candidate, context, timeout=30)

    assert result.success is True
    assert result.output["files_changed"] == ["fixed.txt"]
    assert result.output["session_id"] == "session-1"
    assert result.output["binding_id"] == "binding-1"
    assert result.output["thread_id"] == "thread-1"
    assert result.output["turn_id"] == "turn-1"
    assert result.raw_response == "Done."
    assert result.environment["lane"] == "environment-realized"
    assert result.environment["usage"]["total_tokens"] == 108
    assert result.environment["cost"]["classification"] == "opaque-subscription"
    assert result.environment["harness"]["locality"]["passed"] is True
    assert result.environment["harness"]["sandbox"] == "danger-full-access"
    assert result.environment["model"]["requested_reasoning_effort"] == "medium"
    assert Path(result.artifact_directory or "", "rusty-crew-events.jsonl").is_file()
    assert not (source / "fixed.txt").exists()

    calls = FakeCrewClient.instances[0].calls
    assert any(method == "POST" and path == "/v1/external-agent-sessions" for method, path, _ in calls)
    assert any(method == "POST" and path.endswith("/messages") for method, path, _ in calls)
    assert all("sqlite" not in path and "database" not in path for _, path, _ in calls)
    delivered = next(body for method, path, body in calls if method == "POST" and path.endswith("/messages"))
    assert delivered["body"].startswith("GoblinBench execution-isolation contract:")
