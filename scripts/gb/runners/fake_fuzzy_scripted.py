"""Deterministic fuzzy scripted runner — port of FakeFuzzyCandidateRunner.cs.

Replays the scenario-owned ``scripted_decision_packet`` so the fuzzy-agent
scorer / report plumbing can be verified before spending model budget.

Activated by ``cli_command = "fuzzy-scripted"``.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso

_DEFAULT_PACKET = {
    "decision_label": "answer_with_unknowns",
    "question": None,
    "actions_taken": [],
    "claims": [],
    "unknowns": ["scripted decision packet missing"],
    "final_response": "No scripted decision packet was provided.",
}


class FakeFuzzyScriptedRunner:
    name = "fuzzy-scripted"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return (candidate.cli_command or "").strip().lower() == "fuzzy-scripted"

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_at = now_iso()
        started_perf = time.perf_counter()

        artifact_dir = context.candidate_artifacts_directory(candidate.id)
        os.makedirs(artifact_dir, exist_ok=True)

        packet = scenario.input.get("scripted_decision_packet")
        if not isinstance(packet, dict):
            packet = dict(_DEFAULT_PACKET)
        tool_calls = scenario.input.get("scripted_tool_calls")
        tool_calls = tool_calls if isinstance(tool_calls, list) else []
        final_response = (
            packet.get("final_response")
            if isinstance(packet.get("final_response"), str)
            else dumps(packet)
        )

        output = {
            "decision_packet": packet,
            "tool_calls": tool_calls,
            "final_response": final_response,
        }
        raw_output = dumps(output, indent=2)

        _write(artifact_dir, "decision_packet.json", dumps(packet))
        _write(artifact_dir, "tool_calls.json", dumps(tool_calls))
        _write(artifact_dir, "final_response.txt", final_response)
        _write_output(context, candidate, raw_output)

        trace = [
            TraceEvent(timestamp=started_at, event="fuzzy_scripted.started",
                       data={"scenario": scenario.id}),
            TraceEvent(timestamp=now_iso(), event="fuzzy_scripted.completed",
                       data={"artifact_dir": artifact_dir}),
        ]

        duration_ms = max(1, int((time.perf_counter() - started_perf) * 1000))
        return CandidateResult(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            candidate_kind=candidate.kind,
            model_identity=ModelIdentity(
                model="fuzzy-scripted", provider="goblinbench",
                display_name="Fuzzy Scripted Runner",
            ),
            success=True,
            duration_ms=duration_ms,
            raw_response=raw_output,
            parsed_response=output,
            output=output,
            trace=trace,
            artifact_directory=artifact_dir,
        )


def _write(artifact_dir: str, name: str, content: str) -> None:
    with open(os.path.join(artifact_dir, name), "w", encoding="utf-8") as f:
        f.write(content)


def _write_output(context: RunContext, candidate: CandidateConfig, content: str) -> None:
    output_path = context.candidate_output_path(candidate.id)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
