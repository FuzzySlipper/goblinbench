"""Scorer protocol — port of GoblinBench.Core.IScorer.

A scorer consumes a CandidateResult and produces a ScoreResult. The main loop
runs only scorers declared in the scenario's scoring config (falling back to
all registered scorers when none are declared), mirroring Program.cs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


@runtime_checkable
class Scorer(Protocol):
    id: str
    name: str

    def score(
        self,
        scenario: Scenario,
        candidate: CandidateConfig,
        candidate_result: CandidateResult,
        context: RunContext,
    ) -> ScoreResult: ...
