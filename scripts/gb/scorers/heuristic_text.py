"""Heuristic text scorer — port of HeuristicTextScorer.cs.

Checks candidate output for forbidden markers (TODO/FIXME/HACK/…) and required
mentions/patterns. Declared by 1 scenario.
"""

from __future__ import annotations

from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult

_DEFAULT_FORBIDDEN = [
    "TODO", "FIXME", "HACK", "NotImplementedException",
    "NotSupportedException", "throw new Exception", "placeholder",
    "TBD", "stub", "workaround",
]


class HeuristicTextScorer:
    id = "heuristic-text"
    name = "Heuristic Text Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        text = candidate_result.raw_response or ""
        params = scenario.scoring.params(self.id) if scenario.scoring else {}

        forbidden = list(_DEFAULT_FORBIDDEN)
        extra_forbidden = params.get("forbidden")
        if isinstance(extra_forbidden, list):
            forbidden += [str(x) for x in extra_forbidden if isinstance(x, str)]

        required: list[str] = []
        req = params.get("required")
        if isinstance(req, list):
            required = [str(x) for x in req if isinstance(x, str)]

        found_forbidden = [p for p in forbidden if p and p.lower() in text.lower()]
        missing_required = [p for p in required if p and p.lower() not in text.lower()]

        total_checks = len(forbidden) + len(required)
        violations = len(found_forbidden) + len(missing_required)
        score = max(0.0, 1.0 - (violations / total_checks)) if total_checks > 0 else 1.0

        threshold = scenario.scoring.threshold(self.id, 0.8) if scenario.scoring else 0.8
        passed = score >= threshold

        parts: list[str] = []
        if found_forbidden:
            parts.append(f"{len(found_forbidden)} forbidden marker(s) found: [{', '.join(found_forbidden)}]")
        if missing_required:
            parts.append(f"{len(missing_required)} required pattern(s) missing: [{', '.join(missing_required)}]")
        if not parts:
            parts.append("no violations")
        summary = (
            f"PASS: heuristic-text: {'; '.join(parts)} ({score:.2f})"
            if passed
            else f"FAIL: heuristic-text: {'; '.join(parts)} ({score:.2f})"
        )

        return ScoreResult(
            scorer_id=self.id, scorer_name=self.name, scoring_kind="heuristic",
            success=True, score=score, passed=passed, human_summary=summary,
            explanation=(f"Checked {total_checks} patterns: {len(found_forbidden)} forbidden found, "
                         f"{len(missing_required)} required missing."),
            detail={
                "forbidden_found": found_forbidden,
                "required_missing": missing_required,
                "total_checks": total_checks,
                "violations": violations,
                "text_length": len(text),
            },
        )
