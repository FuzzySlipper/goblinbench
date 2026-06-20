"""Latency scorer — port of LatencyScorer.cs.

Records latency and optional cost metadata. Always succeeds (measurement
scorer). Score = max(0, 1 - duration/max_budget); latency always "passes".

NOTE: latency scores are inherently non-reproducible across runs (duration
varies), so the artifact-diff validation only treats *logic* as authoritative
for this scorer — the formula and pass/fail semantics, not the exact float.
"""

from __future__ import annotations

import json
import math
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


def _num(val: Any, default: float) -> float:
    if val is None:
        return default
    if isinstance(val, bool):
        return float(val)
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4.0)


def _extract_prompt(scenario: Scenario) -> str:
    p = scenario.input.get("prompt")
    if isinstance(p, str):
        return p
    return json.dumps(scenario.input, ensure_ascii=False)


class LatencyScorer:
    id = "latency"
    name = "Latency / Cost Metadata Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        duration_ms = candidate_result.duration_ms
        params = scenario.scoring.params(self.id) if scenario.scoring else {}

        # Cost estimate, only when both per-1k prices are configured.
        estimated_cost = None
        input_cost = params.get("input_cost_per_1k")
        output_cost = params.get("output_cost_per_1k")
        if input_cost is not None and output_cost is not None:
            input_tokens = _estimate_tokens(candidate_result.raw_response or "")
            output_tokens = _estimate_tokens(_extract_prompt(scenario))
            estimated_cost = (
                input_tokens / 1000.0 * _num(input_cost, 0.0)
                + output_tokens / 1000.0 * _num(output_cost, 0.0)
            )

        max_budget_ms = _num(params.get("max_budget_ms"), 30000.0)
        latency_score = max(0.0, 1.0 - (duration_ms / max_budget_ms))
        # latency scoring always "passes" (C# hardcodes threshold 0.0).

        cost_str = f", estimated cost ${estimated_cost:.4f}" if estimated_cost is not None else ""
        summary = f"INFO: latency: {duration_ms}ms{cost_str} (score {latency_score:.2f})"

        explanation = f"Candidate completed in {duration_ms}ms."
        if estimated_cost is not None:
            explanation += f" Estimated cost: ${estimated_cost:.4f}."

        return ScoreResult(
            scorer_id=self.id,
            scorer_name=self.name,
            scoring_kind="metadata",
            success=True,
            score=latency_score,
            passed=True,
            explanation=explanation,
            human_summary=summary,
            detail={
                "duration_ms": duration_ms,
                "latency_score": latency_score,
                "max_budget_ms": max_budget_ms,
                "estimated_cost_usd": estimated_cost,
            },
        )
