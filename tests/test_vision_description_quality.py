from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.models import CandidateConfig, CandidateResult, Scenario, ScoringConfig  # type: ignore[import-not-found]  # noqa: E402
from gb.runners.vision import _scenario_system_prompt  # type: ignore[import-not-found]  # noqa: E402
from gb.scorers.vision_description_quality import VisionDescriptionQualityScorer  # type: ignore[import-not-found]  # noqa: E402


def _scenario(manifest: dict) -> Scenario:
    return Scenario(
        id="vision.describe-chaotic-desk",
        suite="vision",
        input={"response_schema": "vision_description_v1"},
        scoring=ScoringConfig(
            scorers=["vision-description-quality"],
            parameters={"vision-description-quality": {"gold_manifest": manifest, "target_concrete_items": 6}},
            thresholds={"vision-description-quality": 0.7},
        ),
    )


def _manifest() -> dict:
    return {
        "required_mentions": [
            {"id": "red_mug", "aliases": ["red mug", "cup"], "region": "lower right", "importance": 2},
            {"id": "open_notebook", "aliases": ["open notebook", "notebook"], "region": "center", "importance": 2},
            {"id": "yellow_sticky_note", "aliases": ["yellow sticky note", "post it"], "region": "upper left", "importance": 1},
            {"id": "tangled_cable", "aliases": ["tangled cable", "cable"], "region": "lower left", "importance": 1},
        ],
        "relationship_expectations": [
            {"subject": "red_mug", "relation": "beside", "object": "open_notebook"},
        ],
        "visible_text": [
            {"text": "TODO", "strict": False},
        ],
        "forbidden_claims": ["fire extinguisher", "person"],
        "ambiguous_items": ["small dark object"],
    }


def _score(response: dict, manifest: dict | None = None):
    scorer = VisionDescriptionQualityScorer()
    scenario = _scenario(manifest or _manifest())
    result = CandidateResult(parsed_response=response, output=response, success=True)
    context = RunContext(repo_root=str(REPO), runs_root=str(REPO / "runs"))
    return scorer.score(scenario, CandidateConfig(id="scripted"), result, context)


def test_vision_description_scorer_rewards_concrete_region_aware_description() -> None:
    response = {
        "scene_summary": "A cluttered desk with an open notebook in the center, a red mug in the lower right, sticky notes, and cables.",
        "salient_regions": [
            {"region": "upper left", "description": "A yellow sticky note marked TODO sits near the top edge."},
            {"region": "center", "description": "An open notebook occupies the center of the desk."},
            {"region": "lower right", "description": "A red mug is beside the open notebook."},
            {"region": "lower left", "description": "A tangled cable crosses the lower-left corner."},
        ],
        "objects_and_entities": [
            {"label": "red mug", "location": "lower right", "attributes": ["red", "beside notebook"]},
            {"label": "open notebook", "location": "center", "attributes": ["open"]},
            {"label": "yellow sticky note", "location": "upper left", "attributes": ["TODO text"]},
            {"label": "tangled cable", "location": "lower left", "attributes": ["black"]},
        ],
        "relationships": ["The red mug is beside the open notebook."],
        "text_observed": ["TODO"],
        "uncertainties": ["A small dark object near the edge is ambiguous."],
        "answer": "The image is chaotic but shows a desk with concrete visible items in several regions.",
        "confidence": 0.86,
        "hallucination_risk": "low",
    }

    score = _score(response)

    assert score.passed is True
    assert score.score is not None and score.score > 0.8
    assert score.detail["coverage"]["required_hit"] == 4
    assert score.detail["hallucination"]["forbidden_claims_found"] == []


def test_vision_description_scorer_penalizes_vague_summary() -> None:
    response = {
        "scene_summary": "A cluttered image with many things.",
        "salient_regions": [],
        "objects_and_entities": [],
        "relationships": [],
        "text_observed": [],
        "uncertainties": [],
        "answer": "It is a busy image with various items.",
        "confidence": 0.9,
        "hallucination_risk": "medium",
    }

    score = _score(response)

    assert score.passed is False
    assert score.detail["failure_category"] == "vague_summary"
    assert "few_structured_items" in score.detail["vagueness"]["flags"]


def test_vision_description_scorer_penalizes_forbidden_hallucination() -> None:
    response = {
        "scene_summary": "A cluttered desk with a fire extinguisher and a person in the background.",
        "salient_regions": [{"region": "center", "description": "A person holds a fire extinguisher."}],
        "objects_and_entities": [{"label": "fire extinguisher", "location": "center", "attributes": ["red"]}],
        "relationships": [],
        "text_observed": [],
        "uncertainties": [],
        "answer": "There is a fire extinguisher visible.",
        "confidence": 0.95,
        "hallucination_risk": "low",
    }

    score = _score(response)

    assert score.passed is False
    assert score.detail["failure_category"] == "hallucinated_forbidden_claim"
    assert "fire extinguisher" in score.detail["hallucination"]["forbidden_claims_found"]


def test_vision_description_scorer_tracks_distractor_resistance() -> None:
    manifest = _manifest()
    manifest["distractor_mentions"] = ["skeleton", "particles", "CHAOS BOSS", "hill"]
    response = {
        "scene_summary": "A game HUD shows HEALTH 23% in the upper left and LOW HEALTH in the upper center, but the center has skeletons, particles, a CHAOS BOSS, and a hill.",
        "salient_regions": [
            {"region": "upper left", "description": "HEALTH 23% and MANA 61% are visible."},
            {"region": "upper center", "description": "LOW HEALTH warning."},
            {"region": "lower right", "description": "Ammo 7 / 30."},
        ],
        "objects_and_entities": [
            {"label": "HEALTH 23%", "location": "upper left", "attributes": ["HUD"]},
            {"label": "LOW HEALTH", "location": "upper center", "attributes": ["warning"]},
            {"label": "7 / 30", "location": "lower right", "attributes": ["ammo"]},
        ],
        "relationships": ["LOW HEALTH is in the upper center HUD."],
        "text_observed": ["HEALTH 23%", "LOW HEALTH", "7 / 30"],
        "uncertainties": ["The central skeletons are visual noise."],
        "answer": "The actionable state is the HUD; health is low and ammo is 7 / 30.",
        "confidence": 0.86,
        "hallucination_risk": "low",
    }

    score = _score(response, manifest)

    assert score.detail["distractor_resistance"]["score"] < 1.0
    assert "skeleton" in score.detail["distractor_resistance"]["hits"]


def test_vision_runner_uses_scenario_description_prompt_for_description_schema() -> None:
    scenario = Scenario(input={"response_schema": "vision_description_v1"})
    prompt = _scenario_system_prompt(scenario, CandidateConfig(system_prompt="candidate default"))

    assert "scene_summary" in prompt
    assert "objects_and_entities" in prompt
    assert "candidate default" not in prompt


def test_vision_runner_prefers_explicit_scenario_system_prompt() -> None:
    scenario = Scenario(input={"system_prompt": "scenario-specific contract"})
    prompt = _scenario_system_prompt(scenario, CandidateConfig(system_prompt="candidate default"))

    assert prompt == "scenario-specific contract"
