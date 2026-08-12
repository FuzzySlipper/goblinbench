from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.models import (  # type: ignore[import-not-found]  # noqa: E402
    CandidateConfig,
    CandidateResult,
    Scenario,
    ScoringConfig,
)
from gb.scorers.heuristic_text import HeuristicTextScorer  # type: ignore[import-not-found]  # noqa: E402


def test_roleplay_uses_scenario_markers_without_coding_placeholder_defaults() -> None:
    scenario = Scenario(
        id="roleplay-prose.test",
        suite="roleplay-prose",
        scoring=ScoringConfig(
            scorers=["heuristic-text"],
            parameters={"heuristic-text": {"forbidden": ["palpable tension"]}},
        ),
    )
    result = CandidateResult(
        candidate_id="c",
        success=True,
        raw_response="Her stubborn hope lasted beside the candle stub.",
    )
    context = RunContext(
        run_id="run-test",
        started_at="2026-01-01T00:00:00Z",
        run_directory="/tmp/run-test",
        runs_root="/tmp",
        repo_root=str(REPO),
        scenario_id=scenario.id,
    )

    scored = HeuristicTextScorer().score(
        scenario, CandidateConfig(id="c"), result, context,
    )

    assert scored.score == 1.0
    assert scored.detail["forbidden_found"] == []


def test_single_word_style_marker_does_not_match_inside_another_word() -> None:
    scenario = Scenario(
        id="roleplay-prose.test",
        suite="roleplay-prose",
        scoring=ScoringConfig(
            scorers=["heuristic-text"],
            parameters={"heuristic-text": {"forbidden": ["ache"]}},
        ),
    )
    result = CandidateResult(
        candidate_id="c", success=True, raw_response="Vale reached for his wallet.",
    )
    context = RunContext(
        run_id="run-test",
        started_at="2026-01-01T00:00:00Z",
        run_directory="/tmp/run-test",
        runs_root="/tmp",
        repo_root=str(REPO),
        scenario_id=scenario.id,
    )

    scored = HeuristicTextScorer().score(
        scenario, CandidateConfig(id="c"), result, context,
    )

    assert scored.score == 1.0
    assert scored.detail["forbidden_found"] == []
