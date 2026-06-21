"""No-Op scorer — port of NoOpScorer.cs. Always returns a perfect score.

Useful for smoke-testing the harness. Declared by 1 scenario.
"""

from __future__ import annotations

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


class NoOpScorer:
    id = "noop"
    name = "No-Op Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        return ScoreResult(
            scorer_id=self.id,
            scorer_name=self.name,
            success=True,
            score=1.0,
            passed=True,
            explanation="NoOp scorer: always passes.",
            detail={
                "scenario": scenario.id,
                "candidate": candidate.id if candidate is not None else None,
            },
        )
