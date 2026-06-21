"""Exact-decision scorer — port of ExactDecisionScorer.cs.

Checks a candidate output field against an expected value via deep JSON
equality (after normalizing strings/numbers). Declared by 1 scenario.
"""

from __future__ import annotations

import json
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


class ExactDecisionScorer:
    id = "exact-decision"
    name = "Exact Decision Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        params = scenario.scoring.params(self.id) if scenario.scoring else {}
        expected = params.get("expected")

        if expected is None:
            return ScoreResult(
                scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
                success=False,
                error="No 'expected' value configured in scorer parameters.",
                human_summary="FAIL: exact-decision: no expected value configured",
            )

        field = _string_param(params, "field") or "decision"
        actual = _extract_field(candidate_result, field)

        expected_json = json.dumps(expected, ensure_ascii=False)
        actual_json = json.dumps(actual, ensure_ascii=False) if actual is not None else "null"

        match = _deep_equal(_normalize(expected), _normalize(actual))
        threshold = scenario.scoring.threshold(self.id, 0.5) if scenario.scoring else 0.5
        score = 1.0 if match else 0.0
        passed = score >= threshold
        summary = (
            f"PASS: decision matched expected '{expected_json}' (1.0)"
            if match
            else f"FAIL: decision '{actual_json}' did not match expected '{expected_json}' (0.0)"
        )

        return ScoreResult(
            scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
            success=True, score=score, passed=passed, human_summary=summary,
            explanation=(
                "Output field matched expected value."
                if match
                else f"Output field '{actual_json}' != expected '{expected_json}'."
            ),
            detail={
                "expected": expected,
                "actual": actual,
                "field": params.get("field", "decision"),
                "match": match,
            },
        )


def _extract_field(result: CandidateResult, field: str) -> Any:
    """Try parsed_response → output (dict access) → raw_response, mirroring C#."""
    source = result.parsed_response if isinstance(result.parsed_response, dict) else result.output
    if source is None:
        return result.raw_response
    if isinstance(source, dict):
        if field in source:
            return source[field]
        return source
    # Non-dict: serialize + attempt field extraction.
    try:
        raw = json.dumps(source, default=str)
        doc = json.loads(raw)
        if isinstance(doc, dict) and field in doc:
            return doc[field]
    except (ValueError, TypeError):
        pass
    return source


def _normalize(value: Any) -> Any:
    """Normalize a value for comparison: trim strings, unwrap numbers (port of C# Normalise)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return value
    return value


def _deep_equal(a: Any, b: Any) -> bool:
    """Structural equality with normalized string/number handling (port of JsonElement.DeepEquals)."""
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_deep_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_deep_equal(a[k], b[k]) for k in a)
    return a == b


def _string_param(params: dict[str, Any], key: str) -> str | None:
    v = params.get(key)
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)
