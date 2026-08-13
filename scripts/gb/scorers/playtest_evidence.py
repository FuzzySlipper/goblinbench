"""GoblinBench scorer entry point for interactive playtest evidence.

The contract helpers live in ``gb.playtest_evidence`` so the runner and report
can share exactly the same validation rules.  This module is the maintained
scorer location exposed to the registry and downstream imports.
"""

from ..playtest_evidence import (  # noqa: F401
    PAIR_OUTCOMES,
    PLAYTEST_OUTCOMES,
    PLAYTEST_SCORER_ID,
    PlaytestEvidenceScorer,
    archive_selected_evidence,
    apply_pairwise_outcomes,
    evaluate_playtest_evidence,
)

__all__ = [
    "PAIR_OUTCOMES",
    "PLAYTEST_OUTCOMES",
    "PLAYTEST_SCORER_ID",
    "PlaytestEvidenceScorer",
    "archive_selected_evidence",
    "apply_pairwise_outcomes",
    "evaluate_playtest_evidence",
]
