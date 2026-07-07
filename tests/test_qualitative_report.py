from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.store import DbPaths, ingest_run, open_db  # type: ignore[import-not-found]  # noqa: E402


def load_cli_module(filename: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fake_repo(tmp_path: Path) -> DbPaths:
    root = tmp_path / "repo"
    (root / "runs").mkdir(parents=True)
    (root / "suites" / "qualitative").mkdir(parents=True)
    (root / "scripts" / "gb").mkdir(parents=True)
    scenario = {
        "id": "qualitative.sample",
        "version": "1.0.0",
        "name": "Sample qualitative prompt",
        "suite": "qualitative",
        "description": "Compare concise planning prose.",
        "input": {"prompt": "Explain how to organize a small benchmark campaign."},
        "scoring": {"scorers": ["noop"]},
    }
    (root / "suites" / "qualitative" / "sample.json").write_text(json.dumps(scenario), encoding="utf-8")
    return DbPaths(repo_root=root, runs_root=root / "runs", db_path=root / "runs" / "goblinbench.sqlite")


def patch_cli_paths(monkeypatch: pytest.MonkeyPatch, paths: DbPaths, *modules: ModuleType) -> None:
    for module in modules:
        monkeypatch.setattr(module.DbPaths, "resolve", classmethod(lambda cls, repo_root=None: paths))


def write_qual_run(root: Path, run_id: str = "run-qual-001") -> Path:
    run_dir = root / "runs" / run_id
    results = []
    candidate_results = []
    for candidate_id, model, output in [
        ("model-one", "model-one", "Make a table, run each model once, and summarize briefly."),
        ("model-two", "model-two", "Define a campaign id, store raw artifacts, repeat prompt variants, and compare outputs side-by-side with judge commentary."),
    ]:
        cell_dir = run_dir / "scenarios" / "qualitative.sample" / "candidates" / candidate_id
        cell_dir.mkdir(parents=True)
        (cell_dir / "output.json").write_text(output, encoding="utf-8")
        (cell_dir / "scores.json").write_text(json.dumps([{"scorer_id": "noop"}]), encoding="utf-8")
        candidate_results.append({
            "candidate_id": candidate_id,
            "candidate_name": candidate_id,
            "candidate_kind": "OpenAiModel",
            "success": True,
            "duration_ms": 100,
            "artifact_directory": str(cell_dir),
            "model_identity": {
                "model": model,
                "provider": "test-provider",
                "display_name": f"test-provider/{model}",
            },
            "scores": [{
                "scorer_id": "noop",
                "scorer_name": "NoOp",
                "scoring_kind": "deterministic",
                "success": True,
                "score": 1.0,
                "passed": True,
                "human_summary": "ok",
                "detail": {},
            }],
        })
    results.append({
        "scenario_id": "qualitative.sample",
        "scenario_version": "1.0.0",
        "candidate_results": candidate_results,
    })
    run = {
        "run_id": run_id,
        "started_at": "2026-07-06T00:00:00Z",
        "completed_at": "2026-07-06T00:00:01Z",
        "label": "qual fixture",
        "results": results,
    }
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    return run_dir / "run.json"


def ingest_fixture(paths: DbPaths) -> None:
    conn = open_db(paths.db_path)
    try:
        ingest_run(conn, write_qual_run(paths.repo_root), paths.repo_root)
    finally:
        conn.close()


def test_qual_report_dry_run_writes_prompt_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_repo: DbPaths) -> None:
    gb_qual = load_cli_module("gb-qual-report.py", "gb_qual_report_dry_run_test")
    patch_cli_paths(monkeypatch, fake_repo, gb_qual)
    ingest_fixture(fake_repo)

    out = tmp_path / "qual.md"
    rc = gb_qual.main([
        "--runs", "run-qual-001",
        "--dry-run",
        "--out", str(out),
        "--campaign", "unit-campaign",
    ])

    assert rc == 0
    report = out.read_text(encoding="utf-8")
    assert "GoblinBench Qualitative Comparison" in report
    assert "model-one" in report
    assert "model-two" in report
    request = out.parent / "judge-requests" / "qualitative.sample.md"
    assert request.is_file()
    prompt = request.read_text(encoding="utf-8")
    assert "Candidate A" in prompt
    assert "Candidate B" in prompt
    assert "Explain how to organize" in prompt


def test_qual_report_uses_saved_judge_response(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_repo: DbPaths) -> None:
    gb_qual = load_cli_module("gb-qual-report.py", "gb_qual_report_saved_response_test")
    patch_cli_paths(monkeypatch, fake_repo, gb_qual)
    ingest_fixture(fake_repo)
    response_dir = tmp_path / "responses"
    response_dir.mkdir()
    (response_dir / "qualitative.sample.json").write_text(json.dumps({
        "scenario_id": "qualitative.sample",
        "overall_commentary": "B is more repeatable and artifact-aware.",
        "rankings": [
            {"label": "B", "rank": 1, "score": 9, "summary": "best", "strengths": ["repeatable"], "weaknesses": []},
            {"label": "A", "rank": 2, "score": 6, "summary": "thin", "strengths": ["concise"], "weaknesses": ["too shallow"]},
        ],
        "caveats": [],
    }), encoding="utf-8")

    out = tmp_path / "qual.md"
    rc = gb_qual.main([
        "--runs", "run-qual-001",
        "--judge-response-dir", str(response_dir),
        "--out", str(out),
        "--campaign", "unit-campaign",
    ])

    assert rc == 0
    report = out.read_text(encoding="utf-8")
    assert "B is more repeatable" in report
    assert "| 1 | B | model-two | 9.0 | best" in report
    parsed = out.parent / "judge-responses" / "qualitative.sample.parsed.json"
    assert parsed.is_file()
    parsed_doc = json.loads(parsed.read_text(encoding="utf-8"))
    assert parsed_doc["rankings"][0]["label"] == "B"
