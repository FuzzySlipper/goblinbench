from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.models import CandidateConfig, CandidateKind, Scenario  # type: ignore[import-not-found]  # noqa: E402
from gb.registry import default_runners, pick_runner  # type: ignore[import-not-found]  # noqa: E402
from gb.runners.rusty_crew_native import (  # type: ignore[import-not-found]  # noqa: E402
    RustyCrewNativeConfig,
    RustyCrewNativeRunner,
)
import gb.runners.rusty_crew_native as native_module  # type: ignore[import-not-found]  # noqa: E402


class FakeNativeCrewClient:
    instances: list["FakeNativeCrewClient"] = []
    fixture_dir = ""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url
        self.token = token
        self.calls: list[tuple[str, str, object, object]] = []
        self.delivered = False
        FakeNativeCrewClient.instances.append(self)

    def get(self, path: str, timeout: float):  # type: ignore[no-untyped-def]
        self.calls.append(("GET", path, None, None))
        if path.startswith("/v1/admin/profiles/registry/"):
            return {
                "profileId": "gb-run-test-coding-example-native-candidate",
                "lifecycleStatus": "active", "revision": 1,
                "displayName": "GoblinBench", "providerAlias": "deepseek-flash",
                "localToolProfileId": "full_agent",
                "toolPolicy": {"requestedToolsets": ["local_code_write"]}, "mcpBindings": [],
            }
        if path == "/v1/chat/sessions/native-session":
            return {"session": {
                "session_id": "native-session",
                "effective_defaults": {"resourceLimits": {"workdir": "/home"}},
            }}
        if path == "/v1/chat/sessions/native-session/context":
            return {
                "provider": {
                    "alias": "deepseek-flash", "protocol": "chat_completions",
                    "provider_kind": "custom", "model_id": "deepseek-flash",
                    "context_window_tokens": 128000, "revision": 3,
                },
                "brain": {"module": "chat-completions", "strategy": "default", "backend": "rust"},
                "tools": {"local_tool_profile_id": "full_agent", "tool_count": 12},
            }
        if path.startswith("/v1/chat/sessions/native-session/events?"):
            if not self.delivered:
                return {"items": [], "latest_cursor": "native-session:0", "has_more": False}
            return {"items": [
                {
                    "event_id": "native-session:2", "kind": "tool_call_started",
                    "payload": {"wake_id": "wake-1", "tool_call_id": "tool-1",
                                "tool_name": "terminal", "debug_detail_id": "detail-1"},
                },
                {
                    "event_id": "native-session:3", "kind": "tool_call_completed",
                    "payload": {"wake_id": "wake-1", "tool_call_id": "tool-1",
                                "tool_name": "terminal", "debug_detail_id": "detail-1"},
                },
                {
                    "event_id": "native-session:4", "kind": "assistant_text_delta",
                    "payload": {"wake_id": "wake-1", "text": "Done."},
                },
                {
                    "event_id": "native-session:5", "kind": "assistant_message_completed",
                    "payload": {"wake_id": "wake-1", "status": "completed"},
                },
            ], "latest_cursor": "native-session:5", "has_more": False}
        if path == "/v1/chat/sessions/native-session/tool-calls/detail-1":
            command = f"cd {shlex.quote(FakeNativeCrewClient.fixture_dir)} && pwd"
            return {
                "debug_detail_id": "detail-1", "tool_name": "terminal", "status": "completed",
                "arguments": {"value": {"command": command}, "truncated": False, "redacted": False},
                "final_result": {"value": {"details": {"stdout": FakeNativeCrewClient.fixture_dir + "\n"}}},
            }
        raise AssertionError(f"unexpected GET {path}")

    def post(
        self, path: str, body: dict, timeout: float, headers: dict | None = None  # type: ignore[type-arg]
    ):
        self.calls.append(("POST", path, body, headers))
        if path == "/v1/admin/control/profiles":
            assert body["providerAlias"] == "deepseek-flash"
            return {"outcome": {"status": "completed", "result": {
                "profileId": body["profileId"], "sessionId": "native-session", "agentId": "native-agent",
            }}}
        if path == "/v1/chat/sessions/native-session/messages":
            self.delivered = True
            marker = "Your only workspace is "
            start = body["body"].index(marker) + len(marker)
            FakeNativeCrewClient.fixture_dir = body["body"][start:].split(". Use absolute", 1)[0]
            Path(FakeNativeCrewClient.fixture_dir, "fixed.txt").write_text(
                "fixed through native Crew\n", encoding="utf-8"
            )
            return {
                "status": "accepted", "message_id": "message-1", "wake_id": "wake-1",
                "latest_cursor": "native-session:1",
            }
        if path.endswith("/delete"):
            return {"outcome": {"status": "completed", "result": {"sessionsDeleted": ["native-session"]}}}
        raise AssertionError(f"unexpected POST {path}")


def test_native_runner_routes_before_generic_coding_agent() -> None:
    candidate = CandidateConfig(
        id="native", kind=CandidateKind.CodingAgent,
        config={"runner": "rusty-crew-native", "provider_alias": "deepseek-flash"},
    )
    assert isinstance(pick_runner(default_runners(), candidate), RustyCrewNativeRunner)


def test_native_config_requires_provider_and_refuses_non_debug_endpoint() -> None:
    with pytest.raises(ValueError, match="provider_alias"):
        RustyCrewNativeConfig.from_candidate(CandidateConfig(config={"runner": "rusty-crew-native"}))
    with pytest.raises(ValueError, match="refuses non-debug endpoint"):
        RustyCrewNativeConfig.from_candidate(CandidateConfig(config={
            "runner": "rusty-crew-native", "provider_alias": "deepseek-flash",
            "base_url": "http://127.0.0.1:9347",
        }))


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
        config={"runner": "rusty-crew-native", "provider_alias": "deepseek-flash"},
    )

    result = RustyCrewNativeRunner().run(scenario, candidate, context, timeout=30)

    assert result.success is True, result.error
    assert result.raw_response == "Done."
    assert result.output["files_changed"] == ["fixed.txt"]
    assert result.output["provider_protocol"] == "chat_completions"
    assert result.environment["harness"]["family"] == "crew-native-chat"
    assert result.environment["harness"]["known_limit_task_id"] == 5846
    assert result.environment["harness"]["locality"]["passed"] is True
    assert result.environment["cleanup"]["status"] == "completed"
    assert not (source / "fixed.txt").exists()
    artifacts = Path(result.artifact_directory or "")
    assert (artifacts / "rusty-crew-native-events.jsonl").is_file()
    assert (artifacts / "rusty-crew-native-tool-details.jsonl").is_file()

    calls = FakeNativeCrewClient.instances[0].calls
    assert any(method == "POST" and path == "/v1/admin/control/profiles" for method, path, _, _ in calls)
    assert any(method == "POST" and path.endswith("/messages") for method, path, _, _ in calls)
    assert any(method == "POST" and path.endswith("/delete") for method, path, _, _ in calls)
    assert all("sqlite" not in path and "database" not in path for _, path, _, _ in calls)
