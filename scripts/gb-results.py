#!/usr/bin/env python3
"""GoblinBench SQLite results index and agent-friendly query CLI.

This is intentionally dependency-light: stdlib sqlite3 + argparse only.  Raw
`runs/<run-id>/run.json` artifacts remain the source of evidence; this CLI builds
and queries a compact relational index for fast comparisons.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_DB_NAME = "goblinbench-results.sqlite"
PRIMARY_SCORER_EXCLUDES = {"noop", "latency"}
INFRA_FAILURE_CATEGORIES = {
    "timeout",
    "http_429",
    "http_502",
    "http_503",
    "http_504",
    "rate_limited",
    "provider_error",
    "runner_error",
}


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def default_runs_root() -> Path:
    return repo_root_from_here() / "runs"


def default_db_path(runs_root: Path | None = None) -> Path:
    root = runs_root or default_runs_root()
    return root / DEFAULT_DB_NAME


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    completed_at TEXT,
    label TEXT,
    run_dir TEXT NOT NULL,
    suites_json TEXT NOT NULL DEFAULT '[]',
    scenario_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_sets (
    run_set_id TEXT PRIMARY KEY,
    label TEXT,
    path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_set_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_set_id TEXT NOT NULL REFERENCES run_sets(run_set_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    variant TEXT NOT NULL DEFAULT '',
    suite TEXT NOT NULL DEFAULT '',
    candidate_id TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    UNIQUE (run_set_id, run_id, variant, candidate_id)
);

CREATE TABLE IF NOT EXISTS candidate_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL,
    scenario_version TEXT,
    suite TEXT,
    scenario_name TEXT,
    candidate_id TEXT NOT NULL,
    candidate_name TEXT,
    candidate_kind TEXT,
    model TEXT,
    provider TEXT,
    base_url TEXT,
    display_name TEXT,
    success INTEGER NOT NULL,
    error TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    artifact_directory TEXT,
    primary_scorer_id TEXT,
    primary_score REAL,
    primary_passed INTEGER,
    primary_summary TEXT,
    failure_categories_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_result_id INTEGER NOT NULL REFERENCES candidate_results(id) ON DELETE CASCADE,
    scorer_id TEXT NOT NULL,
    scorer_name TEXT,
    scoring_kind TEXT,
    success INTEGER,
    error TEXT,
    score REAL,
    passed INTEGER,
    explanation TEXT,
    human_summary TEXT,
    judge_model TEXT,
    judge_prompt_version TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS failure_categories (
    candidate_result_id INTEGER NOT NULL REFERENCES candidate_results(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    PRIMARY KEY (candidate_result_id, category)
);

CREATE INDEX IF NOT EXISTS idx_candidate_results_model ON candidate_results(model);
CREATE INDEX IF NOT EXISTS idx_candidate_results_candidate ON candidate_results(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_results_suite ON candidate_results(suite);
CREATE INDEX IF NOT EXISTS idx_candidate_results_run ON candidate_results(run_id);
CREATE INDEX IF NOT EXISTS idx_candidate_results_scenario ON candidate_results(scenario_id);
CREATE INDEX IF NOT EXISTS idx_scores_candidate_result ON scores(candidate_result_id);
CREATE INDEX IF NOT EXISTS idx_failure_categories_category ON failure_categories(category);
CREATE INDEX IF NOT EXISTS idx_run_set_runs_run ON run_set_runs(run_id);
"""


def init_db(conn: sqlite3.Connection, reset: bool = False) -> None:
    if reset:
        conn.executescript(
            """
            DROP TABLE IF EXISTS failure_categories;
            DROP TABLE IF EXISTS scores;
            DROP TABLE IF EXISTS candidate_results;
            DROP TABLE IF EXISTS run_set_runs;
            DROP TABLE IF EXISTS run_sets;
            DROP TABLE IF EXISTS runs;
            DROP TABLE IF EXISTS schema_meta;
            """
        )
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', '1')"
    )
    conn.commit()


def as_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def as_json_list(value: Any) -> str:
    return json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)


def bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def split_scenario(scenario_id: str) -> tuple[str, str]:
    if "." in scenario_id:
        suite, name = scenario_id.split(".", 1)
        return suite, name
    return scenario_id, scenario_id


def primary_score(scores: list[dict[str, Any]], success: bool) -> dict[str, Any] | None:
    for score in scores:
        scorer_id = score.get("scorer_id") or score.get("scorerId") or ""
        if score.get("passed") is not None and scorer_id not in PRIMARY_SCORER_EXCLUDES:
            return score
    for score in scores:
        if (score.get("scorer_id") or score.get("scorerId")) not in PRIMARY_SCORER_EXCLUDES:
            return score
    if scores:
        return scores[0]
    return None


def collect_failure_categories(candidate: dict[str, Any], scores: list[dict[str, Any]]) -> list[str]:
    cats: list[str] = []
    if not candidate.get("success", False):
        cats.append("runner_error")
        err = (candidate.get("error") or "").lower()
        if "timeout" in err or "timed out" in err:
            cats.append("timeout")
        for code in ("429", "502", "503", "504"):
            if code in err:
                cats.append(f"http_{code}")
    for score in scores:
        detail = score.get("detail") or {}
        value = detail.get("failure_categories")
        if isinstance(value, list):
            cats.extend(str(x) for x in value if x)
        elif isinstance(value, str) and value:
            cats.append(value)
    return sorted(set(cats))


def run_json_paths(runs_root: Path) -> list[Path]:
    if not runs_root.exists():
        return []
    return sorted(p for p in runs_root.glob("run-*/run.json") if p.is_file())


def delete_run(conn: sqlite3.Connection, run_id: str) -> None:
    # Cascades remove candidate_results/scores/categories and run_set membership.
    conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))


def import_run_json(conn: sqlite3.Connection, run_json: Path, repo_root: Path) -> tuple[str, int]:
    with run_json.open("r", encoding="utf-8") as f:
        run = json.load(f)

    run_id = run.get("run_id") or run.get("runId") or run_json.parent.name
    delete_run(conn, run_id)

    results = run.get("results") or []
    scenario_ids = [r.get("scenario_id") or r.get("scenarioId") for r in results]
    suites = sorted({split_scenario(s)[0] for s in scenario_ids if s})
    candidate_ids = {
        cr.get("candidate_id") or cr.get("candidateId")
        for sr in results
        for cr in (sr.get("candidate_results") or sr.get("candidateResults") or [])
    }
    rel_run_dir = os.path.relpath(run_json.parent, repo_root)

    conn.execute(
        """
        INSERT INTO runs(run_id, started_at, completed_at, label, run_dir, suites_json,
                         scenario_count, candidate_count, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            run.get("started_at") or run.get("startedAt"),
            run.get("completed_at") or run.get("completedAt"),
            run.get("label"),
            rel_run_dir,
            as_json(suites),
            len(results),
            len([c for c in candidate_ids if c]),
            as_json(run.get("metadata") or {}),
        ),
    )

    inserted_candidates = 0
    for sr in results:
        scenario_id = sr.get("scenario_id") or sr.get("scenarioId") or ""
        suite, scenario_name = split_scenario(scenario_id)
        scenario_version = sr.get("scenario_version") or sr.get("scenarioVersion")
        for cr in sr.get("candidate_results") or sr.get("candidateResults") or []:
            scores = cr.get("scores") or []
            model_identity = cr.get("model_identity") or cr.get("modelIdentity") or {}
            primary = primary_score(scores, bool(cr.get("success", False)))
            failure_categories = collect_failure_categories(cr, scores)
            artifact_dir = cr.get("artifact_directory") or cr.get("artifactDirectory")
            if artifact_dir:
                try:
                    artifact_dir = os.path.relpath(artifact_dir, repo_root) if os.path.isabs(artifact_dir) else artifact_dir
                except ValueError:
                    pass

            cur = conn.execute(
                """
                INSERT INTO candidate_results(
                    run_id, scenario_id, scenario_version, suite, scenario_name,
                    candidate_id, candidate_name, candidate_kind, model, provider, base_url,
                    display_name, success, error, duration_ms, artifact_directory,
                    primary_scorer_id, primary_score, primary_passed, primary_summary,
                    failure_categories_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    scenario_id,
                    scenario_version,
                    suite,
                    scenario_name,
                    cr.get("candidate_id") or cr.get("candidateId") or "",
                    cr.get("candidate_name") or cr.get("candidateName"),
                    cr.get("candidate_kind") or cr.get("candidateKind"),
                    model_identity.get("model"),
                    model_identity.get("provider"),
                    model_identity.get("base_url") or model_identity.get("baseUrl"),
                    model_identity.get("display_name") or model_identity.get("displayName"),
                    1 if cr.get("success", False) else 0,
                    cr.get("error"),
                    int(cr.get("duration_ms") or cr.get("durationMs") or 0),
                    artifact_dir,
                    (primary or {}).get("scorer_id") or (primary or {}).get("scorerId"),
                    (primary or {}).get("score"),
                    bool_to_int((primary or {}).get("passed")),
                    (primary or {}).get("human_summary") or (primary or {}).get("humanSummary"),
                    as_json_list(failure_categories),
                ),
            )
            if cur.lastrowid is None:
                raise RuntimeError("candidate_results insert did not return a row id")
            candidate_result_id = int(cur.lastrowid)
            inserted_candidates += 1

            for score in scores:
                detail = score.get("detail") or {}
                conn.execute(
                    """
                    INSERT INTO scores(candidate_result_id, scorer_id, scorer_name, scoring_kind,
                                       success, error, score, passed, explanation, human_summary,
                                       judge_model, judge_prompt_version, detail_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_result_id,
                        score.get("scorer_id") or score.get("scorerId") or "",
                        score.get("scorer_name") or score.get("scorerName"),
                        score.get("scoring_kind") or score.get("scoringKind"),
                        bool_to_int(score.get("success")),
                        score.get("error"),
                        score.get("score"),
                        bool_to_int(score.get("passed")),
                        score.get("explanation"),
                        score.get("human_summary") or score.get("humanSummary"),
                        score.get("judge_model") or score.get("judgeModel"),
                        score.get("judge_prompt_version") or score.get("judgePromptVersion"),
                        as_json(detail),
                    ),
                )
            for cat in failure_categories:
                conn.execute(
                    "INSERT OR IGNORE INTO failure_categories(candidate_result_id, category) VALUES (?, ?)",
                    (candidate_result_id, cat),
                )
    return run_id, inserted_candidates


def import_run_sets(conn: sqlite3.Connection, runs_root: Path, repo_root: Path) -> int:
    count = 0
    for tsv_path in sorted(runs_root.glob("*/run-ids.tsv")):
        run_set_id = tsv_path.parent.name
        rel_path = os.path.relpath(tsv_path.parent, repo_root)
        conn.execute(
            """
            INSERT OR REPLACE INTO run_sets(run_set_id, label, path, metadata_json)
            VALUES (?, ?, ?, COALESCE((SELECT metadata_json FROM run_sets WHERE run_set_id = ?), '{}'))
            """,
            (run_set_id, run_set_id, rel_path, run_set_id),
        )
        conn.execute("DELETE FROM run_set_runs WHERE run_set_id = ?", (run_set_id,))
        with tsv_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 4:
                    continue
                variant, suite, candidate_id, run_id = row[:4]
                duration = None
                if len(row) >= 5:
                    try:
                        duration = float(row[4])
                    except ValueError:
                        duration = None
                exists = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                if not exists:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO run_set_runs(
                        run_set_id, run_id, variant, suite, candidate_id, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run_set_id, run_id, variant or "", suite or "", candidate_id or "", duration),
                )
                count += 1
    return count


def import_runs(args: argparse.Namespace) -> int:
    runs_root = Path(args.runs_root).resolve()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else runs_root.parent
    db_path = Path(args.db).resolve() if args.db else default_db_path(runs_root)
    conn = open_db(db_path)
    init_db(conn, reset=args.reset)
    paths = run_json_paths(runs_root)
    candidate_count = 0
    with conn:
        for path in paths:
            try:
                _, inserted = import_run_json(conn, path, repo_root)
                candidate_count += inserted
            except Exception as exc:  # keep a bad historical run from blocking the index
                print(f"warning: failed to import {path}: {exc}", file=sys.stderr)
        run_set_links = import_run_sets(conn, runs_root, repo_root)
    if not args.quiet:
        print(f"Imported {len(paths)} run(s), {candidate_count} candidate-result row(s), {run_set_links} run-set link(s)")
        print(f"DB: {db_path}")
    return 0


def ensure_db(args: argparse.Namespace) -> sqlite3.Connection:
    runs_root = Path(args.runs_root).resolve() if getattr(args, "runs_root", None) else default_runs_root()
    db_path = Path(args.db).resolve() if getattr(args, "db", None) else default_db_path(runs_root)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}\nRun: {Path(__file__).name} import --db {db_path}")
    return open_db(db_path)


def add_common_filters(where: list[str], params: list[Any], args: argparse.Namespace, alias: str = "cr") -> None:
    if getattr(args, "suite", None):
        where.append(f"{alias}.suite = ?")
        params.append(args.suite)
    if getattr(args, "model", None):
        models = split_csv(args.model)
        if len(models) == 1:
            where.append(f"({alias}.model = ? OR {alias}.candidate_id = ?)")
            params.extend([models[0], models[0]])
        else:
            placeholders = ",".join("?" for _ in models)
            where.append(f"({alias}.model IN ({placeholders}) OR {alias}.candidate_id IN ({placeholders}))")
            params.extend(models)
            params.extend(models)
    if getattr(args, "candidate", None):
        candidates = split_csv(args.candidate)
        placeholders = ",".join("?" for _ in candidates)
        where.append(f"{alias}.candidate_id IN ({placeholders})")
        params.extend(candidates)
    if getattr(args, "run_set", None):
        where.append(
            f"EXISTS (SELECT 1 FROM run_set_runs rsr WHERE rsr.run_id = {alias}.run_id AND rsr.run_set_id = ?)"
        )
        params.append(args.run_set)


def split_csv(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        raw = [value]
    else:
        raw = list(value)
    out: list[str] = []
    for item in raw:
        out.extend(part.strip() for part in str(item).split(",") if part.strip())
    return out


def pass_expr(alias: str = "cr") -> str:
    return f"CASE WHEN {alias}.primary_passed = 1 THEN 1 WHEN {alias}.primary_passed IS NULL AND {alias}.success = 1 THEN 1 ELSE 0 END"


def infra_expr(alias: str = "cr") -> str:
    clauses = [f"{alias}.success = 0"]
    for cat in INFRA_FAILURE_CATEGORIES:
        clauses.append(
            f"EXISTS (SELECT 1 FROM failure_categories fc WHERE fc.candidate_result_id = {alias}.id AND fc.category = '{cat}')"
        )
    return "CASE WHEN " + " OR ".join(clauses) + " THEN 1 ELSE 0 END"


def query_rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def command_runs(args: argparse.Namespace) -> int:
    conn = ensure_db(args)
    where: list[str] = []
    params: list[Any] = []
    add_common_filters(where, params, args, alias="cr")
    if getattr(args, "run_id", None):
        where.append("r.run_id = ?")
        params.append(args.run_id)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    limit_sql = "" if args.limit == 0 else "LIMIT ?"
    if args.limit != 0:
        params.append(args.limit)
    rows = query_rows(
        conn,
        f"""
        SELECT r.run_id,
               r.started_at,
               r.completed_at,
               COALESCE(GROUP_CONCAT(DISTINCT rsr.run_set_id), '') AS run_sets,
               r.suites_json AS suites,
               COUNT(DISTINCT cr.scenario_id) AS scenarios,
               COUNT(DISTINCT cr.candidate_id) AS candidates,
               COUNT(*) AS cells,
               SUM({pass_expr('cr')}) AS pass,
               COUNT(*) AS total,
               ROUND(AVG(cr.primary_score), 4) AS avg_score,
               ROUND(AVG(cr.duration_ms), 1) AS avg_duration_ms,
               COALESCE(GROUP_CONCAT(DISTINCT COALESCE(cr.model, cr.candidate_id)), '') AS models,
               r.run_dir
        FROM runs r
        JOIN candidate_results cr ON cr.run_id = r.run_id
        LEFT JOIN run_set_runs rsr ON rsr.run_id = r.run_id
        {where_sql}
        GROUP BY r.run_id
        ORDER BY r.run_id DESC
        {limit_sql}
        """,
        params,
    )
    for row in rows:
        row["pass_rate"] = rate(row.get("pass"), row.get("total"))
        row["suites"] = ",".join(json.loads(row["suites"] or "[]"))
    return emit(rows, args.format, columns=["run_id", "run_sets", "suites", "scenarios", "candidates", "pass", "total", "pass_rate", "avg_score", "avg_duration_ms", "models", "run_dir"])


def command_run_sets(args: argparse.Namespace) -> int:
    conn = ensure_db(args)
    rows = query_rows(
        conn,
        """
        SELECT rs.run_set_id,
               rs.path,
               COUNT(DISTINCT rsr.run_id) AS runs,
               COALESCE(GROUP_CONCAT(DISTINCT rsr.variant), '') AS variants,
               COALESCE(GROUP_CONCAT(DISTINCT rsr.suite), '') AS suites,
               COALESCE(GROUP_CONCAT(DISTINCT rsr.candidate_id), '') AS candidates
        FROM run_sets rs
        LEFT JOIN run_set_runs rsr ON rsr.run_set_id = rs.run_set_id
        GROUP BY rs.run_set_id
        ORDER BY rs.run_set_id DESC
        """,
    )
    return emit(rows, args.format, columns=["run_set_id", "runs", "variants", "suites", "candidates", "path"])


def command_compare(args: argparse.Namespace) -> int:
    conn = ensure_db(args)
    group = args.by
    group_sql = {
        "model": "COALESCE(cr.model, cr.candidate_id)",
        "candidate": "cr.candidate_id",
        "provider": "COALESCE(cr.provider, '—')",
        "suite": "cr.suite",
    }[group]
    where: list[str] = []
    params: list[Any] = []
    add_common_filters(where, params, args, alias="cr")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = query_rows(
        conn,
        f"""
        SELECT {group_sql} AS {group},
               COALESCE(cr.provider, '') AS provider,
               COUNT(DISTINCT cr.run_id) AS runs,
               COUNT(DISTINCT cr.scenario_id) AS scenarios,
               COUNT(*) AS cells,
               SUM({pass_expr('cr')}) AS pass,
               COUNT(*) AS total,
               ROUND(AVG(cr.primary_score), 4) AS avg_score,
               ROUND(AVG(cr.duration_ms), 1) AS avg_duration_ms,
               SUM(CASE WHEN cr.success = 0 THEN 1 ELSE 0 END) AS runner_failures,
               SUM({infra_expr('cr')}) AS infra_failures,
               COALESCE(GROUP_CONCAT(DISTINCT cr.suite), '') AS suites
        FROM candidate_results cr
        {where_sql}
        GROUP BY {group_sql}, COALESCE(cr.provider, '')
        ORDER BY CAST(SUM({pass_expr('cr')}) AS REAL) / COUNT(*) DESC, AVG(cr.primary_score) DESC, cells DESC
        """,
        params,
    )
    for row in rows:
        row["pass_rate"] = rate(row.get("pass"), row.get("total"))
    cols = [group, "provider", "runs", "scenarios", "cells", "pass", "total", "pass_rate", "avg_score", "avg_duration_ms", "runner_failures", "infra_failures", "suites"]
    return emit(rows, args.format, columns=cols)


def command_model(args: argparse.Namespace) -> int:
    conn = ensure_db(args)
    where: list[str] = []
    params: list[Any] = []
    args.model = args.model_name
    add_common_filters(where, params, args, alias="cr")
    group_sql = "cr.scenario_id" if args.by == "scenario" else "cr.suite"
    label = "scenario_id" if args.by == "scenario" else "suite"
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = query_rows(
        conn,
        f"""
        SELECT {group_sql} AS {label},
               COUNT(DISTINCT cr.run_id) AS runs,
               COUNT(DISTINCT cr.candidate_id) AS candidates,
               COUNT(*) AS cells,
               SUM({pass_expr('cr')}) AS pass,
               COUNT(*) AS total,
               ROUND(AVG(cr.primary_score), 4) AS avg_score,
               ROUND(AVG(cr.duration_ms), 1) AS avg_duration_ms,
               SUM(CASE WHEN cr.success = 0 THEN 1 ELSE 0 END) AS runner_failures,
               SUM({infra_expr('cr')}) AS infra_failures,
               COALESCE(GROUP_CONCAT(DISTINCT cr.candidate_id), '') AS candidate_ids
        FROM candidate_results cr
        {where_sql}
        GROUP BY {group_sql}
        ORDER BY {label}
        """,
        params,
    )
    for row in rows:
        row["pass_rate"] = rate(row.get("pass"), row.get("total"))
    cols = [label, "runs", "candidates", "cells", "pass", "total", "pass_rate", "avg_score", "avg_duration_ms", "runner_failures", "infra_failures", "candidate_ids"]
    return emit(rows, args.format, columns=cols)


def expected_scenarios(repo_root: Path, suite: str) -> list[str]:
    suite_dir = repo_root / "suites" / suite
    scenarios: list[str] = []
    if not suite_dir.exists():
        raise SystemExit(f"suite directory not found: {suite_dir}")
    for path in sorted(suite_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            declared_suite = data.get("suite")
            scenario_id = data.get("id") or f"{suite}.{path.stem}"
            # Some smoke scenarios live in this directory but declare a different suite.
            if declared_suite and declared_suite != suite:
                continue
        except Exception:
            scenario_id = f"{suite}.{path.stem}"
        scenarios.append(str(scenario_id))
    return scenarios


def command_coverage(args: argparse.Namespace) -> int:
    if not args.suite:
        raise SystemExit("coverage requires --suite")
    conn = ensure_db(args)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    expected = expected_scenarios(repo_root, args.suite)

    filters: list[str] = []
    params: list[Any] = []
    add_common_filters(filters, params, args, alias="cr")
    where_sql = "WHERE " + " AND ".join(filters)
    rows_by_scenario = {
        row["scenario_id"]: dict(row)
        for row in conn.execute(
            f"""
            SELECT cr.scenario_id,
                   COUNT(DISTINCT cr.run_id) AS runs,
                   COUNT(DISTINCT cr.candidate_id) AS candidates,
                   COUNT(*) AS cells,
                   SUM({pass_expr('cr')}) AS pass,
                   COUNT(*) AS total,
                   ROUND(AVG(cr.primary_score), 4) AS avg_score,
                   ROUND(AVG(cr.duration_ms), 1) AS avg_duration_ms,
                   COALESCE(GROUP_CONCAT(DISTINCT COALESCE(cr.model, cr.candidate_id)), '') AS models,
                   COALESCE(GROUP_CONCAT(DISTINCT cr.candidate_id), '') AS candidate_ids
            FROM candidate_results cr
            {where_sql}
            GROUP BY cr.scenario_id
            """,
            params,
        ).fetchall()
    }

    output: list[dict[str, Any]] = []
    for scenario_id in expected:
        row = rows_by_scenario.get(scenario_id, {"scenario_id": scenario_id})
        total = int(row.get("total") or 0)
        row["present"] = "yes" if total else "no"
        row["missing"] = "no" if total else "yes"
        row.setdefault("runs", 0)
        row.setdefault("candidates", 0)
        row.setdefault("cells", 0)
        row.setdefault("pass", 0)
        row.setdefault("total", 0)
        row["pass_rate"] = rate(row.get("pass"), row.get("total"))
        row.setdefault("avg_score", None)
        row.setdefault("avg_duration_ms", None)
        row.setdefault("models", "")
        row.setdefault("candidate_ids", "")
        output.append(row)

    columns = ["scenario_id", "present", "missing", "runs", "candidates", "cells", "pass", "total", "pass_rate", "avg_score", "models", "candidate_ids"]
    return emit(output, args.format, columns=columns)


def command_failures(args: argparse.Namespace) -> int:
    conn = ensure_db(args)
    where: list[str] = [f"({pass_expr('cr')} = 0 OR cr.success = 0)"]
    params: list[Any] = []
    add_common_filters(where, params, args, alias="cr")
    where_sql = "WHERE " + " AND ".join(where)
    limit_sql = "" if args.limit == 0 else "LIMIT ?"
    if args.limit != 0:
        params.append(args.limit)
    rows = query_rows(
        conn,
        f"""
        SELECT cr.run_id,
               cr.suite,
               cr.scenario_id,
               COALESCE(cr.model, cr.candidate_id) AS model,
               cr.provider,
               cr.candidate_id,
               cr.primary_score AS score,
               cr.primary_passed AS passed,
               cr.success,
               cr.duration_ms,
               cr.primary_scorer_id AS scorer,
               cr.primary_summary AS summary,
               cr.error,
               cr.failure_categories_json AS categories,
               cr.artifact_directory
        FROM candidate_results cr
        {where_sql}
        ORDER BY cr.run_id DESC, cr.suite, cr.scenario_id, model
        {limit_sql}
        """,
        params,
    )
    for row in rows:
        row["categories"] = ",".join(json.loads(row["categories"] or "[]"))
        row["passed"] = tristate(row["passed"])
        row["success"] = "yes" if row["success"] else "no"
    cols = ["run_id", "suite", "scenario_id", "model", "candidate_id", "score", "passed", "success", "categories", "summary", "artifact_directory"]
    return emit(rows, args.format, columns=cols)


def command_cell(args: argparse.Namespace) -> int:
    conn = ensure_db(args)
    params: list[Any] = [args.run_id, args.scenario, args.candidate]
    rows = query_rows(
        conn,
        """
        SELECT cr.* FROM candidate_results cr
        WHERE cr.run_id = ? AND cr.scenario_id = ? AND (cr.candidate_id = ? OR cr.model = ?)
        LIMIT 1
        """,
        [args.run_id, args.scenario, args.candidate, args.candidate],
    )
    if not rows:
        print("cell not found", file=sys.stderr)
        return 1
    row = rows[0]
    scores = query_rows(conn, "SELECT * FROM scores WHERE candidate_result_id = ? ORDER BY id", [row["id"]])
    row["scores"] = scores
    row["failure_categories"] = json.loads(row.pop("failure_categories_json") or "[]")
    return emit([row], args.format, columns=None)


def rate(pass_count: Any, total: Any) -> float:
    try:
        total_i = int(total or 0)
        if total_i == 0:
            return 0.0
        return round(100.0 * int(pass_count or 0) / total_i, 1)
    except Exception:
        return 0.0


def tristate(value: Any) -> str:
    if value is None:
        return "—"
    return "yes" if int(value) == 1 else "no"


def emit(rows: list[dict[str, Any]], fmt: str, columns: list[str] | None) -> int:
    if fmt == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif fmt == "jsonl":
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    elif fmt == "tsv":
        cols = columns or sorted({key for row in rows for key in row})
        print("\t".join(cols))
        for row in rows:
            print("\t".join(format_value(row.get(col)) for col in cols))
    else:
        print_table(rows, columns)
    return 0


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("\n", " ")


def print_table(rows: list[dict[str, Any]], columns: list[str] | None) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = columns or list(rows[0].keys())
    widths: dict[str, int] = {}
    for col in cols:
        widths[col] = min(max(len(col), *(len(format_value(row.get(col))) for row in rows)), 42)
    header = "  ".join(col.ljust(widths[col]) for col in cols)
    print(header)
    print("  ".join("-" * widths[col] for col in cols))
    for row in rows:
        cells = []
        for col in cols:
            text = format_value(row.get(col))
            if len(text) > widths[col]:
                text = text[: max(0, widths[col] - 1)] + "…"
            cells.append(text.ljust(widths[col]))
        print("  ".join(cells))


def add_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help=f"SQLite DB path (default: runs/{DEFAULT_DB_NAME})")
    parser.add_argument("--runs-root", default=str(default_runs_root()), help="Runs directory")


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--suite", help="Filter by suite id, e.g. den-mcp-ambiguity")
    parser.add_argument("--model", help="Filter by model or candidate id; comma-separated accepted")
    parser.add_argument("--candidate", help="Filter by candidate id; comma-separated accepted")
    parser.add_argument("--run-set", help="Filter to a run set imported from runs/<set>/run-ids.tsv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GoblinBench SQLite results CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("import", help="Import run.json artifacts into SQLite")
    add_db_args(p)
    p.add_argument("--repo-root", default=str(repo_root_from_here()), help="Repo root for relativizing artifact paths")
    p.add_argument("--reset", action="store_true", help="Drop and rebuild DB schema before importing")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=import_runs)

    p = sub.add_parser("runs", help="List indexed runs with compact aggregate stats")
    add_db_args(p)
    add_filter_args(p)
    p.add_argument("--run-id", help="Show one run")
    p.add_argument("--limit", type=int, default=30, help="Max rows; 0 for all")
    p.add_argument("--format", choices=["table", "json", "jsonl", "tsv"], default="table")
    p.set_defaults(func=command_runs)

    p = sub.add_parser("run-sets", help="List imported coherent run sets/campaigns")
    add_db_args(p)
    p.add_argument("--format", choices=["table", "json", "jsonl", "tsv"], default="table")
    p.set_defaults(func=command_run_sets)

    p = sub.add_parser("compare", help="Aggregate pass/score/latency by model/candidate/provider/suite")
    add_db_args(p)
    add_filter_args(p)
    p.add_argument("--by", choices=["model", "candidate", "provider", "suite"], default="model")
    p.add_argument("--format", choices=["table", "json", "jsonl", "tsv"], default="table")
    p.set_defaults(func=command_compare)

    p = sub.add_parser("model", help="Show one model/candidate across suites or scenarios")
    add_db_args(p)
    add_filter_args(p)
    p.add_argument("model_name", help="Model id or candidate id")
    p.add_argument("--by", choices=["suite", "scenario"], default="suite")
    p.add_argument("--format", choices=["table", "json", "jsonl", "tsv"], default="table")
    p.set_defaults(func=command_model)

    p = sub.add_parser("coverage", help="Show expected suite scenarios and which are missing for filters")
    add_db_args(p)
    add_filter_args(p)
    p.add_argument("--repo-root", default=str(repo_root_from_here()), help="Repo root for reading suites/<suite>/*.json")
    p.add_argument("--format", choices=["table", "json", "jsonl", "tsv"], default="table")
    p.set_defaults(func=command_coverage)

    p = sub.add_parser("failures", help="List failing cells with categories and artifact pointers")
    add_db_args(p)
    add_filter_args(p)
    p.add_argument("--limit", type=int, default=50, help="Max rows; 0 for all")
    p.add_argument("--format", choices=["table", "json", "jsonl", "tsv"], default="table")
    p.set_defaults(func=command_failures)

    p = sub.add_parser("cell", help="Show one run × scenario × candidate cell, including scorer rows")
    add_db_args(p)
    p.add_argument("run_id")
    p.add_argument("scenario")
    p.add_argument("candidate", help="Candidate id or model id")
    p.add_argument("--format", choices=["json", "jsonl", "table", "tsv"], default="json")
    p.set_defaults(func=command_cell)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
