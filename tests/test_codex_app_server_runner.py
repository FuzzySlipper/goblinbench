from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.models import CandidateConfig, CandidateKind, Scenario  # type: ignore[import-not-found]  # noqa: E402
from gb.registry import default_runners, pick_runner  # type: ignore[import-not-found]  # noqa: E402
from gb.runners.codex_app_server import (  # type: ignore[import-not-found]  # noqa: E402
    CodexAppServerClient,
    CodexAppServerRunner,
    EventCapture,
    NotificationBufferLimitExceeded,
)
import gb.runners.codex_app_server as codex_module  # type: ignore[import-not-found]  # noqa: E402


class FakeCodexClient:
    instances: list["FakeCodexClient"] = []

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self.requests: list[tuple[str, dict]] = []
        self.notifications: list[tuple[str, dict]] = []
        self.events: list[dict] = []
        self.fixture_dir = ""
        FakeCodexClient.instances.append(self)

    def __enter__(self) -> "FakeCodexClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def notify(self, method: str, params: dict) -> None:
        self.notifications.append((method, params))

    def request(self, method: str, params: dict, deadline: float, event_log: list[dict]):  # type: ignore[no-untyped-def]
        self.requests.append((method, params))
        if method == "initialize":
            return {"serverInfo": {"version": "test"}}
        if method == "thread/start":
            self.fixture_dir = params["cwd"]
            return {
                "thread": {"id": "thread-1"},
                "model": params["model"],
                "modelProvider": "openai",
                "reasoningEffort": params["config"]["model_reasoning_effort"],
            }
        if method == "turn/start":
            fixture = Path(self.fixture_dir)
            (fixture / "fixed.txt").write_text("fixed by fake Codex\n", encoding="utf-8")
            command = "/bin/bash -lc pwd"
            self.events = [
                {"method": "item/started", "params": {"item": {
                    "id": "command-1", "type": "commandExecution", "command": command,
                    "cwd": self.fixture_dir, "status": "inProgress",
                }}},
                {"method": "item/completed", "params": {"item": {
                    "id": "command-1", "type": "commandExecution", "command": command,
                    "cwd": self.fixture_dir, "status": "completed", "output": self.fixture_dir + "\n",
                }}},
                {"method": "item/agentMessage/delta", "params": {"delta": "I fixed it."}},
                {"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}},
            ]
            return {"turn": {"id": "turn-1"}}
        raise AssertionError(f"unexpected request {method}")

    def receive(self, timeout: float) -> dict:
        return self.events.pop(0)

    def respond_to_server_request(self, message: dict, event_log: list[dict]) -> None:
        raise AssertionError("fake run should not need approval")


def test_codex_runner_routes_before_generic_coding_agent() -> None:
    candidate = CandidateConfig(
        id="codex", name="codex", kind=CandidateKind.CodingAgent,
        config={"runner": "codex-app-server"},
    )
    assert isinstance(pick_runner(default_runners(), candidate), CodexAppServerRunner)


def test_codex_client_preserves_notifications_arriving_during_request() -> None:
    client = CodexAppServerClient("/tmp/not-connected.sock")
    message = {"method": "turn/completed", "params": {"turn": {"id": "turn-1"}}}
    client.notifications.append((message, 1))
    client.notification_bytes = 1

    assert client.receive(0) == message


def test_codex_client_caps_notification_backlog_while_waiting_for_request_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A non-responsive app-server must not turn streamed notifications into an OOM."""
    client = CodexAppServerClient("/tmp/not-connected.sock", max_notifications=2, max_notification_bytes=1_024)
    received = iter([
        {"method": "item/started", "params": {"item": {"id": "one"}}},
        {"method": "item/updated", "params": {"item": {"id": "two"}}},
        {"method": "item/updated", "params": {"item": {"id": "three"}}},
    ])
    monkeypatch.setattr(client, "_send_json", lambda payload: None)
    monkeypatch.setattr(client, "_receive_from_socket", lambda timeout: next(received))

    with EventCapture(tmp_path / "codex-events.jsonl", max_bytes=4_096) as events:
        with pytest.raises(NotificationBufferLimitExceeded, match="notification backlog"):
            client.request("turn/start", {}, time.monotonic() + 5, events)

    assert (tmp_path / "codex-events.jsonl").read_text(encoding="utf-8").count("item/") == 3


def test_codex_request_does_not_replay_preserved_notifications(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = CodexAppServerClient("/tmp/not-connected.sock")
    notification = {"method": "remoteControl/status/changed", "params": {"status": "disabled"}}
    client.notifications.append((notification, 64))
    client.notification_bytes = 64
    monkeypatch.setattr(client, "_send_json", lambda payload: None)
    monkeypatch.setattr(client, "_receive_from_socket", lambda timeout: {"id": 1, "result": {"thread": {"id": "t1"}}})

    with EventCapture(tmp_path / "codex-events.jsonl", max_bytes=4_096) as events:
        result = client.request("thread/start", {}, time.monotonic() + 1, events)

    assert result == {"thread": {"id": "t1"}}
    assert client.notifications == [(notification, 64)]
    assert (tmp_path / "codex-events.jsonl").read_text(encoding="utf-8").count("remoteControl") == 0


def test_codex_runner_uses_fixture_copy_and_returns_standard_coding_contract(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source = repo / "fixtures" / "coding" / "example"
    source.mkdir(parents=True)
    (source / "input.txt").write_text("canonical\n", encoding="utf-8")
    socket_path = tmp_path / "codex.sock"
    socket_path.touch()
    FakeCodexClient.instances.clear()
    monkeypatch.setattr(codex_module, "CodexAppServerClient", FakeCodexClient)

    context = RunContext(
        run_id="run-test", started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-test"), runs_root=str(tmp_path / "runs"),
        repo_root=str(repo), scenario_id="coding.example",
    )
    scenario = Scenario(id="coding.example", suite="coding", input={"fixture_case": "example", "task": "Create fixed.txt"})
    candidate = CandidateConfig(
        id="codex-candidate", name="Codex Test", kind=CandidateKind.CodingAgent,
        model="gpt-5.6-terra", provider="codex-app-server",
        config={
            "runner": "codex-app-server", "socket_path": str(socket_path),
            "reasoning_effort": "medium", "sandbox": "danger-full-access",
        },
    )

    result = CodexAppServerRunner().run(scenario, candidate, context, timeout=30)

    assert result.success is True
    assert result.error is None
    assert result.output["files_changed"] == ["fixed.txt"]
    assert Path(result.output["fixture_dir"]).joinpath("fixed.txt").read_text() == "fixed by fake Codex\n"
    assert (source / "fixed.txt").exists() is False
    assert result.output["turn_status"] == "completed"
    assert result.output["transport"] == "websocket-over-unix"
    assert result.output["locality"]["passed"] is True
    assert result.output["reasoning_effort"] == "medium"
    artifact_dir = Path(result.artifact_directory or "")
    assert (artifact_dir / "agent.patch").is_file()
    assert (artifact_dir / "codex-events.jsonl").is_file()

    client = FakeCodexClient.instances[0]
    assert [name for name, _ in client.requests] == ["initialize", "thread/start", "turn/start"]
    assert client.requests[0][1]["capabilities"] == {"experimentalApi": True}
    assert client.notifications == [("initialized", {})]
    thread_params = client.requests[1][1]
    assert thread_params["ephemeral"] is True
    assert thread_params["approvalPolicy"] == "never"
    assert thread_params["sandbox"] == "danger-full-access"
    assert thread_params["runtimeWorkspaceRoots"] == [result.output["fixture_dir"]]
    assert thread_params["config"] == {"model_reasoning_effort": "medium"}
    turn_params = client.requests[2][1]
    assert turn_params["effort"] == "medium"
    assert turn_params["cwd"] == result.output["fixture_dir"]
    assert turn_params["runtimeWorkspaceRoots"] == [result.output["fixture_dir"]]
    assert turn_params["input"][0]["text"].startswith("GoblinBench execution-isolation contract:")
    assert turn_params["approvalPolicy"] == "never"
    assert turn_params["sandboxPolicy"] == {"type": "dangerFullAccess"}
