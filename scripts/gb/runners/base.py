"""Candidate runner protocol — port of GoblinBench.Core.ICandidateRunner.

Each runner declares which candidates it ``can_handle`` and implements ``run``.
The main loop dispatches the first registered runner that claims a candidate
(first-match, mirroring C# LINQ ``FirstOrDefault(r => r.CanHandle(...))``).

Runners are synchronous: the Milestone-1 runners (NoOp/Scripted) can't block,
and a sync contract keeps cancellation trivially faithful (a deadline passed
in) without asyncio complexity. Milestone-2 subprocess runners
(CodingAgent/OpenAiChat) will honor the same ``timeout`` via subprocess timeouts.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario


@runtime_checkable
class CandidateRunner(Protocol):
    name: str

    def can_handle(self, candidate: CandidateConfig) -> bool: ...

    def run(
        self,
        scenario: Scenario,
        candidate: CandidateConfig,
        context: RunContext,
        timeout: float | None = None,
    ) -> CandidateResult: ...
