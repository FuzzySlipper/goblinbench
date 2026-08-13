from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from gb.context import RunContext  # type: ignore[import-not-found]  # noqa: E402
from gb.models import (  # type: ignore[import-not-found]  # noqa: E402
    CandidateConfig,
    CandidateKind,
    CandidateResult,
    PerScenarioResult,
    Scenario,
    ScoringConfig,
)
from gb.playtest_evidence import (  # type: ignore[import-not-found]  # noqa: E402
    PlaytestEvidenceScorer,
    archive_selected_evidence,
    apply_pairwise_outcomes,
)
from gb.registry import default_runners, default_scorers, pick_runner  # type: ignore[import-not-found]  # noqa: E402
from gb.runners.interactive_playtest import (  # type: ignore[import-not-found]  # noqa: E402
    InteractivePlaytestConfig,
    InteractivePlaytestRunner,
    _extract_playtest_evidence,
    _verify_target_revision,
    _retryable_infrastructure_error,
)
from gb.store import prune_run_files  # type: ignore[import-not-found]  # noqa: E402


def _scenario(**input_values: object) -> Scenario:
    return Scenario(
        id="interactive-playtest.example",
        suite="interactive-playtest",
        input={
            "expected_revision": "a" * 40,
            "cell_id": "example-cell",
            "cell_class": "known_good",
            "expected_outcome": "pass",
            "pair_id": "pair-1",
            "requires_sequence": True,
            **input_values,
        },
        scoring=ScoringConfig(
            scorers=["playtest-evidence"],
            parameters={"playtest-evidence": {"requires_sequence": True}},
        ),
    )


def _result(tmp_path: Path, candidate_id: str, role: str, outcome: str = "pass") -> CandidateResult:
    (tmp_path / "screenshots").mkdir(exist_ok=True)
    (tmp_path / "screenshots" / f"{candidate_id}.png").write_bytes(b"png")
    index = tmp_path / f"{candidate_id}-playtest-index.json"
    index.write_text(
        json.dumps(
            {
                "revision": {"commit_sha": "a" * 40},
                "status": outcome,
                "cleanup": {"browser_closed": True, "driver_stopped": True},
                "artifacts": [f"screenshots/{candidate_id}.png"],
                "observations": [{"frames": [f"screenshots/{candidate_id}.png", f"screenshots/{candidate_id}.png"]}],
            }
        ),
        encoding="utf-8",
    )
    evidence = {
        "session_id": f"session-{candidate_id}",
        "evidence_index": str(index),
        "finish_outcome": outcome,
        "expected_revision": "a" * 40,
        "cell_id": "example-cell",
        "cell_class": "known_good",
        "local_tool_profile_id": "vision_playtester",
        "pair_id": "pair-1",
        "pair_role": role,
        "assertions": [{"name": "visible result", "pass": outcome == "pass", "artifact": f"screenshots/{candidate_id}.png"}],
        "tool_calls": [
            {"tool_name": "playtest_start"},
            {"tool_name": "playtest_observe"},
            {"tool_name": "playtest_act"},
            {"tool_name": "playtest_finish"},
        ],
    }
    return CandidateResult(
        candidate_id=candidate_id,
        candidate_kind=CandidateKind.CodingAgent,
        success=True,
        output={"playtest_evidence": evidence},
        environment={"profile": {"local_tool_profile_id": "vision_playtester"}},
        artifact_directory=str(tmp_path / candidate_id),
    )


def test_interactive_runner_is_first_class_and_rejects_profile_substitution() -> None:
    candidate = CandidateConfig(
        id="playtest",
        kind=CandidateKind.CodingAgent,
        model="gpt-5.6-luna",
        config={
            "runner": "interactive-playtest",
            "provider_alias": "gpt-5.6-luna",
            "reasoning_effort": "max",
            "local_tool_profile_id": "vision_playtester",
        },
    )
    assert isinstance(pick_runner(default_runners(), candidate), InteractivePlaytestRunner)
    assert any(s.id == "playtest-evidence" for s in default_scorers())
    with pytest.raises(ValueError, match="requires local_tool_profile_id"):
        InteractivePlaytestConfig.from_candidate(
            CandidateConfig(
                id="bad",
                kind=CandidateKind.CodingAgent,
                config={
                    "runner": "interactive-playtest",
                    "provider_alias": "gpt-5.6-luna",
                    "local_tool_profile_id": "full_agent",
                },
            )
        )

    with pytest.raises(ValueError, match="prequalification evidence object"):
        InteractivePlaytestConfig.from_candidate(
            CandidateConfig(
                id="unadmitted",
                kind=CandidateKind.CodingAgent,
                config={
                    "runner": "interactive-playtest",
                    "provider_alias": "gpt-5.6-luna",
                    "local_tool_profile_id": "vision_playtester",
                    "prequalified": True,
                },
            )
        )


def test_exact_revision_rejection_happens_before_live_session() -> None:
    with pytest.raises(ValueError, match="target revision mismatch"):
        _verify_target_revision({"repo_root": str(REPO), "expected_revision": "0" * 40})


def test_infrastructure_retry_is_bounded_to_one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = InteractivePlaytestRunner()
    candidate = CandidateConfig(
        id="retry",
        kind=CandidateKind.CodingAgent,
        config={"runner": "interactive-playtest", "max_infrastructure_retries": 1},
    )
    scenario = _scenario()
    calls = 0

    def fake_once(*_args: object, **_kwargs: object) -> CandidateResult:
        nonlocal calls
        calls += 1
        return CandidateResult(
            success=calls == 2,
            error=None if calls == 2 else "InteractivePlaytestRunner failed: timed out waiting for provider",
            output={"attempt": calls},
        )

    monkeypatch.setattr(runner, "_run_once", fake_once)
    result = runner.run(scenario, candidate, RunContext())
    assert calls == 2
    assert [attempt["attempt"] for attempt in result.output["retry"]["attempts"]] == [0, 1]
    assert _retryable_infrastructure_error("InteractivePlaytestRunner failed: timed out waiting for provider")
    assert not _retryable_infrastructure_error("InteractivePlaytestRunner failed: target revision mismatch")


def test_infrastructure_failure_is_not_adjudicated_as_model_behavior(tmp_path: Path) -> None:
    result = _result(tmp_path, "luna", "incumbent", "fail")
    evidence = result.output["playtest_evidence"]
    evidence["finish_outcome"] = "infrastructure_error"
    scenario = _scenario(expected_outcome="fail")
    score = PlaytestEvidenceScorer().score(scenario, None, result, RunContext())
    assert score.passed is False  # infrastructure is retained but not a behavior result
    assert score.detail["comparison_eligible"] is False


def test_runner_unwraps_native_tool_result_envelope(tmp_path: Path) -> None:
    index = tmp_path / "playtest-index.json"
    evidence = _extract_playtest_evidence(
        [
            {
                "tool_name": "playtest_start",
                "result": {
                    "ok": True,
                    "operation": "start",
                    "value": {
                        "session_id": "broker-session",
                        "index_path": str(index),
                        "revision_binding": {
                            "expected_revision": "a" * 40,
                            "observed_revision": "a" * 40,
                        },
                    },
                },
            },
            {
                "tool_name": "playtest_finish",
                "arguments": {
                    "outcome": "fail",
                    "assertions": [
                        {"name": "visible defect", "pass": False, "artifact": "screenshots/fail.png"}
                    ],
                },
                "result": {
                    "ok": True,
                    "operation": "finish",
                    "value": {"status": "fail", "index_path": str(index)},
                },
            },
        ],
        session_id="native-session",
        expected_revision="a" * 40,
        cell_id="example-cell",
        cell_class="known_good",
        mutation_proof=None,
        mutation_proof_path=None,
        mutation_proof_sha256=None,
        defect_family="known-good",
        campaign_id="campaign",
        repetition=0,
        mission_hash="mission",
        acceptance_hash="acceptance",
        pair_id="pair-1",
        pair_role="incumbent",
    )
    assert evidence["session_id"] == "broker-session"
    assert evidence["finish_outcome"] == "fail"
    assert evidence["evidence_index"] == str(index)
    assert evidence["selected_artifacts"] == ["screenshots/fail.png"]


def test_evidence_contract_rejects_hidden_state_fields(tmp_path: Path) -> None:
    result = _result(tmp_path, "luna", "incumbent", "pass")
    result.output["playtest_evidence"]["tool_calls"].append(
        {"tool_name": "playtest_observe", "arguments": {"dom": True}}
    )
    score = PlaytestEvidenceScorer().score(_scenario(), None, result, RunContext())
    assert score.passed is False
    assert any("forbidden DOM/state/eval" in error for error in score.detail["errors"])


def test_evidence_contract_rejects_screenshot_only_transition(tmp_path: Path) -> None:
    result = _result(tmp_path, "luna", "incumbent")
    index = Path(result.output["playtest_evidence"]["evidence_index"])
    index.write_text(
        json.dumps(
            {
                "revision": {"commit_sha": "a" * 40},
                "status": "pass",
                "cleanup": {"browser_closed": True, "driver_stopped": True},
                "artifacts": ["screenshots/luna.png"],
                "observations": [{"screenshot": "screenshots/luna.png"}],
            }
        ),
        encoding="utf-8",
    )
    score = PlaytestEvidenceScorer().score(_scenario(), None, result, RunContext())
    assert score.success is True
    assert score.score is None
    assert score.passed is False
    assert any("sequence" in error for error in score.detail["errors"])


def test_known_good_false_positive_is_incorrect_not_a_win(tmp_path: Path) -> None:
    result = _result(tmp_path, "luna", "incumbent", "pass")
    result.output["playtest_evidence"]["assertions"][0]["pass"] = False
    score = PlaytestEvidenceScorer().score(_scenario(), None, result, RunContext())
    assert score.passed is True
    assert score.detail["behavioral_status"] == "incorrect"


def test_mutation_cell_requires_proof_handle(tmp_path: Path) -> None:
    result = _result(tmp_path, "challenger", "challenger", "fail")
    evidence = result.output["playtest_evidence"]
    evidence["cell_class"] = "mutation"
    evidence["cell_id"] = "mutation-cell"
    score = PlaytestEvidenceScorer().score(
        _scenario(cell_id="mutation-cell", cell_class="mutation", expected_outcome="fail"),
        None,
        result,
        RunContext(),
    )
    assert score.passed is False
    assert any("mutation-proof" in error for error in score.detail["errors"])


def test_mutation_proof_json_must_bind_the_exact_revision(tmp_path: Path) -> None:
    result = _result(tmp_path, "challenger", "challenger", "fail")
    proof = tmp_path / "mutation-proof.json"
    proof.write_text(
        json.dumps({
            "mutation_revision": "b" * 40,
            "worktree_clean": True,
            "source_checks": [{"passed": True}],
        }),
        encoding="utf-8",
    )
    evidence = result.output["playtest_evidence"]
    evidence.update({
        "cell_class": "mutation",
        "cell_id": "mutation-cell",
        "mutation_proof": "proof-handle",
        "mutation_proof_path": str(proof),
        "mutation_proof_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
    })
    score = PlaytestEvidenceScorer().score(
        _scenario(cell_id="mutation-cell", cell_class="mutation", expected_outcome="fail"),
        None,
        result,
        RunContext(),
    )
    assert score.passed is False
    assert any("mutation_revision" in error for error in score.detail["errors"])


def test_pairwise_outcome_is_relational_not_scalar(tmp_path: Path) -> None:
    luna = _result(tmp_path, "luna", "incumbent", "fail")
    challenger = _result(tmp_path, "challenger", "challenger", "pass")
    scenario = _scenario(expected_outcome="pass")
    for result in (luna, challenger):
        result.scores.append(PlaytestEvidenceScorer().score(scenario, None, result, RunContext()))
    decisions = apply_pairwise_outcomes(
        PerScenarioResult(
            scenario_id=scenario.id,
            scenario_version=scenario.version,
            candidate_results=[luna, challenger],
        )
    )
    assert decisions[0]["outcome"] == "challenger_win"
    assert luna.scores[0].score is None
    assert luna.scores[0].detail["pair_outcome"] == "challenger_win"
    assert challenger.output["pairwise"]["outcome"] == "challenger_win"


def test_archive_survives_run_ring_buffer_prune(tmp_path: Path) -> None:
    source_root = tmp_path / "broker" / "session"
    (source_root / "screenshots").mkdir(parents=True)
    (source_root / "screenshots" / "selected.png").write_bytes(b"selected")
    index = source_root / "playtest-index.json"
    index.write_text(
        json.dumps(
            {
                "revision": {"commit_sha": "a" * 40},
                "artifacts": ["screenshots/selected.png"],
            }
        ),
        encoding="utf-8",
    )
    archived = archive_selected_evidence(index, tmp_path / "runs" / "evidence-archive")
    archive_dir = Path(archived["archive_dir"])
    run_old = tmp_path / "runs" / "run-20240101-old"
    run_new = tmp_path / "runs" / "run-20240102-new"
    run_old.mkdir(parents=True)
    run_new.mkdir(parents=True)
    (run_old / "scratch").write_text("old", encoding="utf-8")
    prune_run_files(tmp_path / "runs", keep=1)
    assert not run_old.exists()
    assert (archive_dir / "playtest-index.json").is_file()
    assert (archive_dir / "artifacts" / "screenshots" / "selected.png").is_file()
