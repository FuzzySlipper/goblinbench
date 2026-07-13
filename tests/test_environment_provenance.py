from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from gb.environment import (  # type: ignore[import-not-found]  # noqa: E402
    finalize_environment,
    refresh_environment_outcomes,
)
from gb.models import (  # type: ignore[import-not-found]  # noqa: E402
    CandidateConfig, CandidateKind, CandidateResult, ModelIdentity, Scenario, ScoreResult,
)


def test_finalize_environment_labels_lane_redacts_secrets_and_preserves_outcome() -> None:
    candidate = CandidateConfig(
        id="direct", kind=CandidateKind.OpenAiModel, model="gpt-test", provider="openai",
        config={"reasoning_effort": "medium", "api_key": "do-not-store"},
    )
    result = CandidateResult(
        candidate_id="direct", candidate_kind=CandidateKind.OpenAiModel,
        model_identity=ModelIdentity(model="gpt-resolved", provider="openai"),
        success=True, duration_ms=12,
        scores=[ScoreResult(scorer_id="exact", score=1.0, passed=True, human_summary="ok")],
    )
    envelope = finalize_environment(candidate, Scenario(id="s", version="2"), "openai-chat", result)

    assert envelope["lane"] == "model-core"
    assert envelope["model"]["resolved"] == "gpt-resolved"
    assert envelope["model"]["requested_config"]["api_key"] == "[REDACTED]"
    assert envelope["outcome"]["passed"] is True
    assert envelope["cost"]["classification"] == "unavailable"


def test_finalize_environment_rejects_invented_amount_for_opaque_subscription() -> None:
    candidate = CandidateConfig(
        id="agent", kind=CandidateKind.CodingAgent,
        config={"environment": {"cost": {"classification": "opaque-subscription", "amount": 0.01}}},
    )
    with pytest.raises(ValueError, match="must not claim a numeric amount"):
        finalize_environment(candidate, Scenario(id="s"), "agent", CandidateResult())


def test_refresh_environment_outcomes_uses_post_processed_primary_score() -> None:
    payload = {"results": [{"candidate_results": [{
        "success": True,
        "artifact_directory": "/tmp/cell/artifacts",
        "environment": {"outcome": {"passed": None}},
        "scores": [
            {"scorer_id": "latency", "score": 0.0, "passed": None, "human_summary": "12ms"},
            {"scorer_id": "coding-tests", "score": 1.0, "passed": True, "human_summary": "PASS"},
        ],
    }]}]}

    artifacts = refresh_environment_outcomes(payload)

    outcome = payload["results"][0]["candidate_results"][0]["environment"]["outcome"]
    assert outcome == {
        "runner_success": True,
        "primary_scorer_id": "coding-tests",
        "score": 1.0,
        "passed": True,
        "summary": "PASS",
    }
    assert artifacts[0][0] == "/tmp/cell/artifacts"
