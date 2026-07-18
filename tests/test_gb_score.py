from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_gb_score():  # type: ignore[no-untyped-def]
    path = REPO / "scripts" / "gb-score.py"
    spec = importlib.util.spec_from_file_location("goblinbench_gb_score", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_score_pipeline_resolves_legacy_id_without_suite_prefix() -> None:
    gb_score = _load_gb_score()

    scenario = gb_score.resolve_scenario("e2e-pi-mock")

    assert scenario is not None
    assert scenario["suite"] == "coding-smoke"
    assert scenario["scoring"]["scorers"] == ["coding-tests"]


def test_score_pipeline_recovers_retained_fixture_and_retries_failed_script(
    monkeypatch, tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    gb_score = _load_gb_score()
    run_dir = tmp_path / "run-test"
    candidate_dir = run_dir / "scenarios" / "coding.example" / "candidates" / "candidate"
    fixture = candidate_dir / "fixture"
    artifacts = candidate_dir / "artifacts"
    fixture.mkdir(parents=True)
    artifacts.mkdir()
    (fixture / "fixed.txt").write_text("fixed\n", encoding="utf-8")
    run = {
        "run_id": "run-test",
        "metadata": {},
        "results": [{
            "scenario_id": "coding.example",
            "candidate_results": [{
                "candidate_id": "candidate",
                "success": False,
                "error": "provider request timeout",
                "artifact_directory": str(artifacts),
                "scores": [{
                    "scorer_id": "coding-tests", "scoring_kind": "script",
                    "success": False, "error": "--fixture-dir missing",
                }],
            }],
        }],
    }
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    monkeypatch.setattr(gb_score, "resolve_scenario", lambda _scenario_id: {
        "scoring": {
            "scorers": ["coding-tests"],
            "parameters": {"coding-tests": {"timeout_seconds": 333}},
            "thresholds": {},
        }
    })
    monkeypatch.setattr(
        gb_score, "discover_scorer_scripts",
        lambda: {"coding-tests": Path("coding-tests.py")},
    )
    observed = {}

    def fake_run(  # type: ignore[no-untyped-def]
        _script, fixture_dir, _artifacts, _params, _threshold, timeout=120,
    ):
        observed["fixture_dir"] = fixture_dir
        observed["timeout"] = timeout
        return {
            "scorer_id": "coding-tests", "scoring_kind": "script",
            "success": True, "score": 1.0, "passed": True,
            "human_summary": "PASS", "detail": {},
        }

    monkeypatch.setattr(gb_score, "run_scorer_script", fake_run)

    assert gb_score.score_run(str(run_dir), retry_failed=True) == 0

    updated = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    result = updated["results"][0]["candidate_results"][0]
    assert observed["fixture_dir"] == str(fixture.resolve())
    assert observed["timeout"] == 333
    assert result["output"]["fixture_recovery"]["source"] == "retained_candidate_fixture"
    assert result["scores"][0]["passed"] is True
    assert result["scores"][0]["detail"]["fixture_recovered_after_runner_failure"] is True
    assert updated["metadata"]["post_score_events"][-1]["scores_written"] == 1
    assert (candidate_dir / "scores.json").is_file()


def test_score_pipeline_refreshes_in_process_fuzzy_score(tmp_path: Path) -> None:
    gb_score = _load_gb_score()
    run_dir = tmp_path / "run-fuzzy"
    artifacts = run_dir / "scenarios" / "evidence-grounding.sample" / "candidates" / "model" / "artifacts"
    artifacts.mkdir(parents=True)
    run = {
        "run_id": "run-fuzzy",
        "metadata": {},
        "results": [{
            "scenario_id": "evidence-grounding.sample",
            "candidate_results": [{
                "candidate_id": "model", "candidate_kind": "OpenAiModel", "success": True,
                "artifact_directory": str(artifacts),
                "output": {"decision_packet": {
                    "decision_label": "answer_with_unknowns", "actions_taken": [],
                    "claims": [], "unknowns": ["Whether an independent review occurred"],
                    "final_response": "Completion cannot be verified from self-report alone.",
                }},
                "scores": [{
                    "scorer_id": "fuzzy-agent-behavior", "scoring_kind": "deterministic",
                    "success": True, "score": 0.8, "passed": False,
                }],
            }],
        }],
    }
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    scenario = {
        "id": "evidence-grounding.sample", "version": "1", "suite": "evidence-grounding",
        "input": {"expected_behavior": {
            "label": "answer_with_unknowns",
            "required_unknowns": [
                ["verified completion", "completion cannot be verified"],
                ["review verdict", "independent review"],
            ],
        }},
        "scoring": {"scorers": ["fuzzy-agent-behavior"]},
    }
    original = gb_score.resolve_scenario
    gb_score.resolve_scenario = lambda _scenario_id: scenario
    try:
        assert gb_score.score_run(str(run_dir), refresh_in_process=True) == 0
    finally:
        gb_score.resolve_scenario = original

    updated = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    score = updated["results"][0]["candidate_results"][0]["scores"][0]
    assert score["passed"] is True
    assert score["score"] == 1.0
    assert score["detail"]["rescored_from_retained_artifacts"] is True
