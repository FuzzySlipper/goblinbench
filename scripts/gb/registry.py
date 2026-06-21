"""Runner + scorer registries and first-match dispatch.

Mirrors Program.cs: runners and scorers are ordered lists; the first runner
that claims a candidate wins. The order matters — e.g. ScriptedRunner must
precede NoOpRunner so that ``cli_command=scripted`` isn't shadowed by NoOp's
catch-all ``Kind=Unknown`` match (see the comment in Program.cs).

New ports (OpenAiChat, CodingAgent, CodingTestScorer, ...) append here.
"""

from __future__ import annotations

from typing import Iterable

from .context import RunContext
from .models import CandidateConfig, CandidateResult, Scenario, ScoreResult
from .runners import (
    CodingAgentRunner,
    CodingScriptedRunner,
    FakeFuzzyScriptedRunner,
    FakeMcpScriptedRunner,
    NoOpRunner,
    OpenAiChatRunner,
    OpenAiFuzzyAgentRunner,
    OpenAiMcpSessionRunner,
    OpenAiMcpToolUseRunner,
    ScriptedRunner,
    VisionCandidateRunner,
)
from .runners.base import CandidateRunner
from .scorers import (
    ExactDecisionScorer,
    FuzzyAgentBehaviorScorer,
    HeuristicTextScorer,
    LatencyScorer,
    McpSessionTrajectoryScorer,
    McpToolUseScorer,
    NoOpScorer,
    OrchestratorDecisionScorer,
    SchemaComplianceScorer,
    VisionCorrectnessScorer,
)
from .scorers.base import Scorer


def default_runners() -> list[CandidateRunner]:
    # ORDER-SENSITIVE. Matches the C# registration order in Program.cs so that
    # first-match dispatch resolves the same way for every candidate:
    #   - specific cli_command runners precede the generic ones
    #   - Scripted / CodingScripted / Fake* claim by cli_command
    #   - specialized OpenAiModel runners claim by cli_command/config.runner
    #   - Vision keys on cli_command only (any kind)
    #   - CodingAgent claims by kind=CodingAgent
    #   - OpenAiChatRunner claims remaining kind=OpenAiModel (plain chat)
    #   - NoOp is the catch-all (Kind=Unknown or cli_command=noop)
    return [
        ScriptedRunner(),
        CodingScriptedRunner(),
        FakeMcpScriptedRunner(),
        FakeFuzzyScriptedRunner(),
        OpenAiMcpToolUseRunner(),
        OpenAiFuzzyAgentRunner(),
        OpenAiMcpSessionRunner(),
        VisionCandidateRunner(),
        CodingAgentRunner(),
        OpenAiChatRunner(),
        NoOpRunner(),
    ]


def default_scorers() -> list[Scorer]:
    # ORDER-DOES-NOT-MATTER for scorers (the main loop runs only those declared
    # by the scenario, resolved by id). Listed in rough usage frequency.
    return [
        LatencyScorer(),
        SchemaComplianceScorer(),
        OrchestratorDecisionScorer(),
        McpToolUseScorer(),
        VisionCorrectnessScorer(),
        FuzzyAgentBehaviorScorer(),
        McpSessionTrajectoryScorer(),
        NoOpScorer(),
        ExactDecisionScorer(),
        HeuristicTextScorer(),
        # CodingTestScorer is already the Python plugin scripts/scorers/coding-tests.py
        # (invoked by gb-score.py); not duplicated here.
        # LlmJudgeScorer is a placeholder (0 scenario uses) — not ported.
        # ElectronFlowScorer depends on the dead Electron runner — not ported.
    ]


def pick_runner(
    runners: Iterable[CandidateRunner], candidate: CandidateConfig
) -> CandidateRunner | None:
    for r in runners:
        if r.can_handle(candidate):
            return r
    return None


def active_scorers(all_scorers: list[Scorer], scenario: Scenario) -> list[Scorer]:
    """Resolve which scorers fire: the scenario's declared list, or all if none.

    Mirrors Program.cs: when scoring.scorers is set, filter the registry to
    those ids (case-insensitive); declared ids not in the registry are silently
    skipped — those are handled later by gb-score.py (e.g. structure-metrics).
    """
    declared = scenario.scoring.scorers if scenario.scoring and scenario.scoring.scorers else None
    if not declared:
        return list(all_scorers)
    declared_lower = [d.lower() for d in declared]
    return [s for s in all_scorers if s.id.lower() in declared_lower]
