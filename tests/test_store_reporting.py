from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb import store as gb_store_core  # type: ignore[import-not-found]  # noqa: E402
from gb.store import DbPaths, ingest_run, open_db, prune_run_files  # type: ignore[import-not-found]  # noqa: E402


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
    (root / "suites").mkdir()
    (root / "scripts" / "gb").mkdir(parents=True)
    return DbPaths(repo_root=root, runs_root=root / "runs", db_path=root / "runs" / "goblinbench.sqlite")


def write_run(root: Path, run_id: str = "run-test-001", *, suite: str = "orchestrator") -> Path:
    run_dir = root / "runs" / run_id
    cell_dir = run_dir / "scenarios" / f"{suite}.sample" / "candidates" / "scripted-deterministic"
    cell_dir.mkdir(parents=True)
    (cell_dir / "output.json").write_text(json.dumps({"decision": "proceed"}), encoding="utf-8")
    (cell_dir / "scores.json").write_text(json.dumps([{"scorer_id": "schema-compliance"}]), encoding="utf-8")
    (cell_dir / "agent.patch").write_text("diff --git a/x b/x\n", encoding="utf-8")
    run = {
        "run_id": run_id,
        "started_at": "2026-06-21T00:00:00Z",
        "completed_at": "2026-06-21T00:00:01Z",
        "label": "unit fixture",
        "results": [
            {
                "scenario_id": f"{suite}.sample",
                "scenario_version": "1.0.0",
                "candidate_results": [
                    {
                        "candidate_id": "scripted-deterministic",
                        "candidate_name": "Scripted",
                        "candidate_kind": "Unknown",
                        "success": True,
                        "duration_ms": 7,
                        "artifact_directory": str(cell_dir),
                        "model_identity": {
                            "model": "scripted",
                            "provider": "local",
                            "display_name": "scripted/local",
                        },
                        "scores": [
                            {
                                "scorer_id": "schema-compliance",
                                "scorer_name": "Schema Compliance",
                                "scoring_kind": "deterministic",
                                "success": True,
                                "score": 1.0,
                                "passed": True,
                                "human_summary": "schema ok",
                                "explanation": "all required fields present",
                                "detail": {"checked": ["decision"]},
                            },
                            {
                                "scorer_id": "latency",
                                "scorer_name": "Latency",
                                "scoring_kind": "metadata",
                                "success": True,
                                "score": 0.0,
                                "passed": None,
                                "human_summary": "7ms",
                                "detail": {},
                            },
                        ],
                    }
                ],
            }
        ],
    }
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    return run_dir / "run.json"


def patch_cli_paths(monkeypatch: pytest.MonkeyPatch, paths: DbPaths, *modules: ModuleType) -> None:
    for module in modules:
        monkeypatch.setattr(module.DbPaths, "resolve", classmethod(lambda cls, repo_root=None: paths))


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_repo_root_detection_no_longer_requires_dotnet_src() -> None:
    root = gb_store_core._default_repo_root()
    assert root == REPO
    assert (root / "suites").is_dir()
    assert (root / "scripts" / "gb").is_dir()
    assert not (root / "src").exists()


def test_ingest_run_is_idempotent_and_inlines_clickthrough_artifacts(fake_repo: DbPaths) -> None:
    run_json = write_run(fake_repo.repo_root)
    conn = open_db(fake_repo.db_path)
    try:
        assert ingest_run(conn, run_json, fake_repo.repo_root) == ("run-test-001", 1)
        assert ingest_run(conn, run_json, fake_repo.repo_root) == ("run-test-001", 1)
        assert count_rows(conn, "runs") == 1
        assert count_rows(conn, "candidate_results") == 1
        assert count_rows(conn, "scores") == 2
        artifacts = conn.execute("SELECT name, content_bytes, external_path FROM artifacts ORDER BY name").fetchall()
        names = {row["name"] for row in artifacts}
        assert {"output.json", "scores.json", "agent.patch"}.issubset(names)
        assert all(row["content_bytes"] is not None for row in artifacts)
        assert all(row["external_path"] is None for row in artifacts)
    finally:
        conn.close()


def test_prune_run_files_keeps_db_history_intact(fake_repo: DbPaths) -> None:
    conn = open_db(fake_repo.db_path)
    try:
        for index in range(3):
            run_json = write_run(fake_repo.repo_root, f"run-test-00{index}")
            ingest_run(conn, run_json, fake_repo.repo_root)
        assert count_rows(conn, "runs") == 3
    finally:
        conn.close()

    pruned = prune_run_files(fake_repo.runs_root, keep=1)
    assert len(pruned) == 2
    assert len([p for p in fake_repo.runs_root.glob("run-*") if p.is_dir()]) == 1

    conn = open_db(fake_repo.db_path)
    try:
        assert count_rows(conn, "runs") == 3
    finally:
        conn.close()


def test_store_delete_safety_rules(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake_repo: DbPaths) -> None:
    gb_store_cli = load_cli_module("gb-store.py", "gb_store_cli_for_delete_test")
    patch_cli_paths(monkeypatch, fake_repo, gb_store_cli)
    conn = open_db(fake_repo.db_path)
    try:
        for run_id, suite in [("run-a", "orchestrator"), ("run-b", "coding")]:
            ingest_run(conn, write_run(fake_repo.repo_root, run_id, suite=suite), fake_repo.repo_root)
    finally:
        conn.close()

    assert gb_store_cli.main(["delete"]) == 0
    assert "Nothing matched" in capsys.readouterr().out

    assert gb_store_cli.main(["delete", "--suite", "coding"]) == 2
    refused = capsys.readouterr()
    assert "Refusing filter-based delete without --yes" in refused.err

    assert gb_store_cli.main(["delete", "--run-id", "run-a", "--files"]) == 0
    deleted = capsys.readouterr().out
    assert "Deleted 1 run(s)" in deleted
    assert not (fake_repo.runs_root / "run-a").exists()

    conn = open_db(fake_repo.db_path)
    try:
        assert [r["run_id"] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id")] == ["run-b"]
    finally:
        conn.close()


def test_report_generates_html_from_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_repo: DbPaths) -> None:
    gb_report_cli = load_cli_module("gb-report.py", "gb_report_cli_for_render_test")
    patch_cli_paths(monkeypatch, fake_repo, gb_report_cli)
    conn = open_db(fake_repo.db_path)
    try:
        ingest_run(conn, write_run(fake_repo.repo_root), fake_repo.repo_root)
    finally:
        conn.close()

    out = tmp_path / "report.html"
    rc = gb_report_cli.main([
        "--runs", "run-test-001",
        "--view", "grid",
        "--narrative", "Unit smoke narrative.",
        "--out", str(out),
    ])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "Unit smoke narrative." in html
    assert "sample" in html  # grid headers intentionally shorten suite-prefixed scenario ids
    assert "scripted" in html
    assert 'name="viewport"' in html
    assert "Swipe table" in html


def test_report_returns_error_when_filter_matches_no_cells(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_repo: DbPaths, capsys: pytest.CaptureFixture[str]) -> None:
    gb_report_cli = load_cli_module("gb-report.py", "gb_report_cli_for_empty_test")
    patch_cli_paths(monkeypatch, fake_repo, gb_report_cli)
    open_db(fake_repo.db_path).close()

    rc = gb_report_cli.main(["--suite", "missing", "--out", str(tmp_path / "empty.html")])
    assert rc == 1
    assert "No cells matched" in capsys.readouterr().err


def test_coding_tests_scorer_no_longer_detects_dotnet_fixtures(tmp_path: Path) -> None:
    scorer = load_cli_module("scorers/coding-tests.py", "coding_tests_scorer_no_dotnet_test")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "OldTests.csproj").write_text("<Project />", encoding="utf-8")

    assert scorer.detect_language(str(fixture)) is None


def test_maintainability_metrics_support_typescript_fixture() -> None:
    metrics = load_cli_module("maintainability-metrics.py", "maintainability_metrics_ts_fixture_test")
    fixture = REPO / "fixtures" / "coding" / "maintainability-mini-service-ts"

    result = metrics.run_metrics(
        str(fixture),
        source_root="src",
        baseline_path=".goblinbench/maintainability-baseline.json",
        central_paths=["src/router.ts", "src/container.ts", "src/handlers/customers.ts"],
        setup_paths=["src/container.ts"],
        handler_paths=["src/handlers/customers.ts"],
    )

    assert result["baseline_available"] is True
    assert result["current"]["source_files"] == 8
    assert result["current"]["max_handler_function_lines"] > 0
    assert result["deltas"]["changed_file_count"] == 0
    assert set(result["current"]["files"]).issuperset({
        "src/handlers/customers.ts",
        "src/validation.ts",
        "src/repository.ts",
    })


def test_typescript_maintainability_scenario_points_at_existing_fixture() -> None:
    scenario_path = REPO / "suites" / "coding" / "maintainability-mini-service-typescript.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    fixture_case = scenario["input"]["fixture_case"]
    fixture = REPO / "fixtures" / "coding" / fixture_case
    assert fixture.is_dir()
    assert (fixture / "package.json").is_file()
    assert scenario["scoring"]["parameters"]["maintainability-metrics"]["source_root"] == "src"

    scorer = load_cli_module("scorers/coding-tests.py", "coding_tests_scorer_ts_fixture_test")
    assert scorer.detect_language(str(fixture)) == "typescript"


def test_maintainability_metrics_support_go_fixture() -> None:
    metrics = load_cli_module("maintainability-metrics.py", "maintainability_metrics_go_fixture_test")
    fixture = REPO / "fixtures" / "coding" / "maintainability-mini-service-go"

    result = metrics.run_metrics(
        str(fixture),
        source_root=".",
        baseline_path=".goblinbench/maintainability-baseline.json",
        central_paths=["router.go", "container.go", "customers.go"],
        setup_paths=["container.go"],
        handler_paths=["customers.go"],
    )

    assert result["baseline_available"] is True
    assert result["current"]["source_files"] == 8
    assert result["current"]["max_handler_function_lines"] > 0
    assert result["deltas"]["changed_file_count"] == 0
    assert "bulk_import_test.go" not in result["current"]["files"]
    assert set(result["current"]["files"]).issuperset({
        "customers.go",
        "validation.go",
        "repository.go",
    })


def test_go_maintainability_scenario_points_at_existing_fixture() -> None:
    scenario_path = REPO / "suites" / "coding" / "maintainability-mini-service-go.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    fixture_case = scenario["input"]["fixture_case"]
    fixture = REPO / "fixtures" / "coding" / fixture_case
    assert fixture.is_dir()
    assert (fixture / "go.mod").is_file()
    assert scenario["scoring"]["parameters"]["maintainability-metrics"]["source_root"] == "."

    scorer = load_cli_module("scorers/coding-tests.py", "coding_tests_scorer_go_fixture_test")
    assert scorer.detect_language(str(fixture)) == "go"


def test_maintainability_metrics_support_rust_fixture() -> None:
    metrics = load_cli_module("maintainability-metrics.py", "maintainability_metrics_rust_fixture_test")
    fixture = REPO / "fixtures" / "coding" / "maintainability-mini-service-rust"

    result = metrics.run_metrics(
        str(fixture),
        source_root="src",
        baseline_path=".goblinbench/maintainability-baseline.json",
        central_paths=["src/router.rs", "src/container.rs", "src/customers.rs"],
        setup_paths=["src/container.rs"],
        handler_paths=["src/customers.rs"],
    )

    assert result["baseline_available"] is True
    assert result["current"]["source_files"] == 9
    assert result["current"]["max_handler_function_lines"] > 0
    assert result["deltas"]["changed_file_count"] == 0
    assert "tests/bulk_import.rs" not in result["current"]["files"]
    assert set(result["current"]["files"]).issuperset({
        "src/customers.rs",
        "src/validation.rs",
        "src/repository.rs",
    })


def test_rust_maintainability_scenario_points_at_existing_fixture() -> None:
    scenario_path = REPO / "suites" / "coding" / "maintainability-mini-service-rust.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    fixture_case = scenario["input"]["fixture_case"]
    fixture = REPO / "fixtures" / "coding" / fixture_case
    assert fixture.is_dir()
    assert (fixture / "Cargo.toml").is_file()
    assert scenario["scoring"]["parameters"]["maintainability-metrics"]["source_root"] == "src"

    scorer = load_cli_module("scorers/coding-tests.py", "coding_tests_scorer_rust_fixture_test")
    assert scorer.detect_language(str(fixture)) == "rust"


def test_structure_metrics_scorer_honors_scan_dir(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    (fixture / "src").mkdir(parents=True)
    (fixture / "tests").mkdir()
    (fixture / "src" / "impl.rs").write_text(
        "pub fn impl_fn(value: i32) -> i32 {\n    value + 1\n}\n",
        encoding="utf-8",
    )
    (fixture / "tests" / "integration.rs").write_text(
        "#[test]\nfn noisy_test() { assert_eq!(1, 1); }\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "scorers" / "structure-metrics.py"),
            "--fixture-dir",
            str(fixture),
            "--params",
            json.dumps({"scan_dir": "src"}),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["success"] is True
    assert result["detail"]["total_impl_files"] == 1
    assert result["detail"]["total_test_files"] == 0
    assert "1 impl files" in result["human_summary"]
