"""Scripted candidate runner — port of ScriptedCandidateRunner.cs.

Returns a canned response read from ``scenario.input.scripted_response``.
Enables deterministic smoke-testing of the full harness pipeline (runners →
scorers → artifacts) without a real model. The scripted_response may be a
JSON object/array/primitive or a raw string; both branches are handled.
"""

from __future__ import annotations

import json
import os
import time

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso


class ScriptedRunner:
    name = "scripted"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return (candidate.cli_command or "").lower() == "scripted"

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_at = now_iso()
        started_perf = time.perf_counter()
        time.sleep(0.001)  # mirrors C# Task.Delay(1)

        raw_response = ""
        parsed = None  # set only when the scripted value is a JSON object

        response_obj = scenario.input.get("scripted_response")

        if response_obj is not None:
            if isinstance(response_obj, str):
                raw_response = response_obj
                try:
                    el = json.loads(response_obj)
                    parsed = el if isinstance(el, dict) else None
                except Exception:
                    pass
            else:
                # dict / list / primitive already deserialized from scenario JSON
                raw_response = json.dumps(response_obj, ensure_ascii=False)
                if isinstance(response_obj, dict):
                    parsed = response_obj

        # Write output.json artifact (raw text, exactly as C# writes it).
        output_path = context.candidate_output_path(candidate.id)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(raw_response)

        # Write trace.jsonl event.
        trace_path = context.candidate_trace_path(candidate.id)
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        event = TraceEvent(
            timestamp=now_iso(),
            event="scripted.response_returned",
            data={"scenario": scenario.id, "candidate": candidate.id},
        )
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(dumps(event, indent=None))
            f.write("\n")

        duration_ms = int((time.perf_counter() - started_perf) * 1000)

        return CandidateResult(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            candidate_kind=candidate.kind,
            model_identity=ModelIdentity(
                model="scripted",
                provider="goblinbench",
                display_name="Scripted Deterministic Runner",
            ),
            success=True,
            duration_ms=duration_ms,
            raw_response=raw_response,
            parsed_response=parsed,
            output=parsed,
            trace=[
                TraceEvent(timestamp=started_at, event="scripted.started"),
                TraceEvent(timestamp=now_iso(), event="scripted.completed"),
            ],
            artifact_directory=context.candidate_artifacts_directory(candidate.id),
        )
