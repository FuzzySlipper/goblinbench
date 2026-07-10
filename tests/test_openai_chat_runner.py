from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.models import CandidateConfig, CandidateKind, Scenario  # type: ignore[import-not-found]  # noqa: E402
from gb.runners.openai_chat import OpenAiChatRunner  # type: ignore[import-not-found]  # noqa: E402


class FakeResponse:
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def getcode(self) -> int:
        return 200

    def read(self) -> bytes:
        return json.dumps({
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "done", "reasoning_content": "thoughts"},
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }).encode("utf-8")


def test_openai_chat_runner_adds_reasoning_and_chat_template_kwargs(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOBLINBENCH_OPENAI_API_KEY", raising=False)

    runner = OpenAiChatRunner()
    scenario = Scenario(id="s", suite="roleplay", input={"prompt": "continue"})
    candidate = CandidateConfig(
        id="c",
        name="c",
        kind=CandidateKind.OpenAiModel,
        model="m",
        provider="p",
        base_url="http://example.invalid/v1",
        config={
            "max_tokens": 8192,
            "temperature": 0.85,
            "reasoning_effort": "high",
            "include_temperature_with_reasoning_effort": True,
            "chat_template_kwargs": {"enable_thinking": True},
        },
    )
    context = RunContext(
        run_id="run-test",
        started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-test"),
        runs_root=str(tmp_path / "runs"),
        repo_root=str(tmp_path),
        scenario_id="s",
    )

    result = runner.run(scenario, candidate, context, timeout=900)

    assert result.success is True
    assert result.raw_response == "done"
    assert captured["timeout"] == 900
    assert captured["body"]["reasoning_effort"] == "high"
    assert captured["body"]["temperature"] == 0.85
    assert captured["body"]["max_tokens"] == 8192
    assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": True}


def test_openai_chat_runner_omits_temperature_by_default_with_reasoning_effort(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout):  # type: ignore[no-untyped-def]
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    runner = OpenAiChatRunner()
    scenario = Scenario(id="s", suite="roleplay", input={"prompt": "continue"})
    candidate = CandidateConfig(
        id="c",
        name="c",
        kind=CandidateKind.OpenAiModel,
        model="m",
        provider="p",
        base_url="http://example.invalid/v1",
        config={"reasoning_effort": "high", "temperature": 0.85},
    )
    context = RunContext(
        run_id="run-test",
        started_at="2026-01-01T00:00:00Z",
        run_directory=str(tmp_path / "runs" / "run-test"),
        runs_root=str(tmp_path / "runs"),
        repo_root=str(tmp_path),
        scenario_id="s",
    )

    runner.run(scenario, candidate, context, timeout=900)

    assert captured["body"]["reasoning_effort"] == "high"
    assert "temperature" not in captured["body"]
