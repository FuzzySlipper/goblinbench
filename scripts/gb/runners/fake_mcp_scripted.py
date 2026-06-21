"""Deterministic fake-MCP scripted runner — port of FakeMcpCandidateRunner.cs.

Replays scenario-owned ``scripted_tool_calls`` / ``scripted_bypass_attempts`` /
``scripted_final_response`` and returns the same output shape a real MCP
tool-use candidate runner produces (``tool_calls``, ``bypass_attempts``,
``final_response``), so the mcp-tool-use scorer / report plumbing can be
verified without spending model budget.

Activated by ``cli_command = "fake-mcp-scripted"``.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso

_DEFAULT_FINAL = "I cannot complete this with the available fake MCP tools."


class FakeMcpScriptedRunner:
    name = "fake-mcp-scripted"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return (candidate.cli_command or "").strip().lower() == "fake-mcp-scripted"

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_at = now_iso()
        started_perf = time.perf_counter()

        tool_calls = _array_input(scenario.input, "scripted_tool_calls")
        bypass_attempts = _array_input(scenario.input, "scripted_bypass_attempts")
        final_response = _string_input(scenario.input, "scripted_final_response") or _DEFAULT_FINAL

        output: dict[str, Any] = {
            "tool_calls": tool_calls,
            "bypass_attempts": bypass_attempts,
            "final_response": final_response,
            "fake_mcp": scenario.input.get("fake_mcp"),
        }
        raw_output = dumps(output, indent=2)

        artifact_dir = context.candidate_artifacts_directory(candidate.id)
        os.makedirs(artifact_dir, exist_ok=True)
        _write(artifact_dir, "tool_calls.json", dumps(tool_calls))
        _write(artifact_dir, "bypass_attempts.json", dumps(bypass_attempts))
        _write(artifact_dir, "final_response.txt", final_response)

        _write_output(context, candidate, raw_output)

        trace: list[TraceEvent] = [
            TraceEvent(timestamp=started_at, event="fake_mcp.started", data={"scenario": scenario.id})
        ]
        for call in tool_calls:
            trace.append(TraceEvent(timestamp=now_iso(), event="fake_mcp.tool_called", data=call))
        for bypass in bypass_attempts:
            trace.append(TraceEvent(timestamp=now_iso(), event="fake_mcp.bypass_attempted", data=bypass))
        trace.append(TraceEvent(
            timestamp=now_iso(), event="fake_mcp.completed",
            data={"tool_call_count": len(tool_calls),
                  "bypass_attempt_count": len(bypass_attempts),
                  "artifact_dir": artifact_dir},
        ))

        duration_ms = max(1, int((time.perf_counter() - started_perf) * 1000))
        return CandidateResult(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            candidate_kind=candidate.kind,
            model_identity=ModelIdentity(
                model="fake-mcp-scripted", provider="goblinbench",
                display_name="Fake MCP Scripted Runner",
            ),
            success=True,
            duration_ms=duration_ms,
            raw_response=raw_output,
            parsed_response=output,
            output=output,
            trace=trace,
            artifact_directory=artifact_dir,
        )


def _array_input(scenario_input: dict[str, Any], key: str) -> list[Any]:
    """Coerce a scenario input value to a list (handles already-parsed arrays
    or a JSON-encoded string). Mirrors C# GetArrayInput."""
    value = scenario_input.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    # Fallback: treat as a single-element list.
    return [value]


def _string_input(scenario_input: dict[str, Any], key: str) -> str | None:
    value = scenario_input.get(key)
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _write(artifact_dir: str, name: str, content: str) -> None:
    with open(os.path.join(artifact_dir, name), "w", encoding="utf-8") as f:
        f.write(content)


def _write_output(context: RunContext, candidate: CandidateConfig, content: str) -> None:
    output_path = context.candidate_output_path(candidate.id)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
