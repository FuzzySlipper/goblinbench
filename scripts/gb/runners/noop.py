"""NoOp candidate runner — port of NoOpCandidateRunner.cs.

Echoes the scenario input and always succeeds. Used for smoke-testing the
harness end to end without a real model or service.
"""

from __future__ import annotations

import os
import time

from ..context import RunContext
from ..models import CandidateConfig, CandidateKind, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso


class NoOpRunner:
    name = "noop"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return (
            candidate.kind == CandidateKind.Unknown
            or (candidate.cli_command or "").lower() == "noop"
        )

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_at = now_iso()
        started_perf = time.perf_counter()

        # Simulate a small amount of work (C# does Task.Delay(10ms)). We use a
        # short sleep; duration drift here is fine — latency scores are never
        # expected to match bit-for-bit across runs.
        time.sleep(0.01)

        output = {
            "echo": scenario.input,
            "status": "noop_ok",
            "message": f"NoOp runner processed scenario '{scenario.id}' for candidate '{candidate.id}'",
        }

        # Write output.json artifact.
        output_path = context.candidate_output_path(candidate.id)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(dumps(output))

        # Write trace.jsonl (single noop.executed event, mirrors C#).
        trace_path = context.candidate_trace_path(candidate.id)
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        executed = TraceEvent(
            timestamp=now_iso(),
            event="noop.executed",
            data={"scenario": scenario.id, "candidate": candidate.id},
        )
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(dumps(executed, indent=None))
            f.write("\n")

        duration_ms = int((time.perf_counter() - started_perf) * 1000)

        return CandidateResult(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            candidate_kind=candidate.kind,
            model_identity=ModelIdentity(
                model="noop",
                provider="goblinbench",
                display_name="No-Op Runner",
            ),
            success=True,
            duration_ms=duration_ms,
            raw_response=dumps(output),
            output=output,
            trace=[
                TraceEvent(timestamp=started_at, event="noop.started"),
                TraceEvent(timestamp=now_iso(), event="noop.completed"),
            ],
            artifact_directory=context.candidate_artifacts_directory(candidate.id),
        )
