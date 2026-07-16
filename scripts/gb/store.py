"""GoblinBench storage layer — the canonical SQLite store.

Single authority over ``runs/goblinbench.sqlite``. Replaces the previous split
where ``runs/<id>/`` files were canonical and the DB was a derived index. Here
the relationship is inverted:

  * The DB is canonical — run metadata, scores, scorer detail, and inline
    artifacts (patches, code samples, score breakdowns) all live as rows.
    Backup is ``cp`` of one file.
  * ``runs/<id>/`` files are scratch space for *this run's* debugging. Written
    as before (so ``grep``/edit work), but bounded by a ring buffer — the N
    most recent runs are kept, older ones auto-pruned. Re-runnable anytime.

Two new tables extend the original gb-results schema:

  * ``artifacts`` — inline content for the artifacts you actually click
    through (patches, output.json, scores.json, traces, code samples). Size-
    tiered: anything under ``INLINE_MAX_BYTES`` is stored as a BLOB; larger
    artifacts (e.g. a 200MB reasoning-model stdout) are referenced by path
    into the (ring-buffered) file tree.
  * ``representative_samples`` — LLM-/scorer-curated excerpts that summarize a
    cell's behavior (e.g. a code sample, a quoted failure reason). The report
    tool and downstream consumers read these instead of re-walking raw files.

This module owns the schema; ``gb-results.py`` and the report tool import from
here rather than re-defining the DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Artifacts larger than this are NOT inlined — they stay as file references
# into the ring-buffered runs/ tree. Tuned so patches/scores/code (the stuff
# you click through) always inline, while raw stdout from reasoning models
# (which can hit hundreds of MB) stays external.
INLINE_MAX_BYTES = 256 * 1024  # 256 KB

# Artifacts to inline by default for a cell — the click-through set.
# Larger ones (stdout.log, stderr.log) are size-tiered automatically.
INLINE_ARTIFACT_NAMES = {
    "patch": "text/plain",
    "output.json": "application/json",
    "scores.json": "application/json",
    "trace.jsonl": "application/x-ndjson",
    "stdout.log": "text/plain",
    "stderr.log": "text/plain",
    "agent.patch": "text/x-diff",
    "environment.json": "application/json",
    "rusty-crew-events.jsonl": "application/x-ndjson",
    "rusty-crew-response.txt": "text/plain",
    "rusty-crew-native-events.jsonl": "application/x-ndjson",
    "rusty-crew-native-tool-details.jsonl": "application/x-ndjson",
    "rusty-crew-native-response.txt": "text/plain",
    "codex-events.jsonl": "application/x-ndjson",
    "codex-response.txt": "text/plain",
}

SCHEMA_VERSION = "3"

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
    run_dir TEXT,
    suites_json TEXT NOT NULL DEFAULT '[]',
    scenario_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_sets (
    run_set_id TEXT PRIMARY KEY,
    label TEXT,
    path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_set_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_set_id TEXT NOT NULL REFERENCES run_sets(run_set_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    variant TEXT NOT NULL DEFAULT '',
    suite TEXT,
    candidate_id TEXT,
    duration_seconds REAL,
    UNIQUE(run_set_id, run_id, variant)
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
    success INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    duration_ms INTEGER,
    artifact_directory TEXT,
    primary_scorer_id TEXT,
    primary_score REAL,
    primary_passed INTEGER,
    primary_summary TEXT,
    primary_explanation TEXT,
    lane TEXT NOT NULL DEFAULT 'model-core',
    environment_name TEXT,
    cost_classification TEXT NOT NULL DEFAULT 'unavailable',
    environment_json TEXT NOT NULL DEFAULT '{}',
    failure_categories_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_result_id INTEGER NOT NULL REFERENCES candidate_results(id) ON DELETE CASCADE,
    scorer_id TEXT NOT NULL,
    scorer_name TEXT,
    scoring_kind TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    score REAL,
    passed INTEGER,
    threshold REAL,
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

-- NEW (storage v2): inline artifacts. content_bytes is NULL when the artifact
-- exceeds INLINE_MAX_BYTES; in that case external_path points into the
-- ring-buffered runs/ tree.
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_result_id INTEGER NOT NULL REFERENCES candidate_results(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    mime TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content_bytes BLOB,
    external_path TEXT,
    UNIQUE(candidate_result_id, name)
);

-- NEW (storage v2): curated excerpts that summarize a cell's behavior. Populated
-- by scorers (structure-metrics already emits per-function detail) or by an
-- LLM pass. The report tool reads these instead of re-walking raw files.
CREATE TABLE IF NOT EXISTS representative_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_result_id INTEGER NOT NULL REFERENCES candidate_results(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    label TEXT,
    language TEXT,
    content TEXT NOT NULL,
    source_path TEXT,
    UNIQUE(candidate_result_id, kind, label)
);

CREATE INDEX IF NOT EXISTS idx_candidate_results_model ON candidate_results(model);
CREATE INDEX IF NOT EXISTS idx_candidate_results_candidate ON candidate_results(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_results_suite ON candidate_results(suite);
CREATE INDEX IF NOT EXISTS idx_candidate_results_run ON candidate_results(run_id);
CREATE INDEX IF NOT EXISTS idx_candidate_results_scenario ON candidate_results(scenario_id);
CREATE INDEX IF NOT EXISTS idx_scores_candidate_result ON scores(candidate_result_id);
CREATE INDEX IF NOT EXISTS idx_failure_categories_category ON failure_categories(category);
CREATE INDEX IF NOT EXISTS idx_run_set_runs_run ON run_set_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_result ON artifacts(candidate_result_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_samples_result ON representative_samples(candidate_result_id);
"""

# Scorer ids that never carry the "primary" pass/fail signal (measurement only).
PRIMARY_SCORER_EXCLUDES = {"noop", "latency"}


@dataclass
class DbPaths:
    """Resolved filesystem paths for the store + ring buffer."""
    repo_root: Path
    runs_root: Path
    db_path: Path

    @classmethod
    def resolve(cls, repo_root: Path | str | None = None) -> "DbPaths":
        repo = Path(repo_root).resolve() if repo_root else _default_repo_root()
        return cls(
            repo_root=repo,
            runs_root=repo / "runs",
            db_path=repo / "runs" / "goblinbench.sqlite",
        )


def _default_repo_root() -> Path:
    d = Path(__file__).resolve().parents[1]
    while True:
        # Python is the canonical runner now; the old .NET src/ tree is not part
        # of repo-root detection. Use durable Python-era anchors instead.
        if (d / "suites").is_dir() and (d / "scripts" / "gb").is_dir():
            return d
        if d.parent == d:
            return Path.cwd()
        d = d.parent


def open_db(db_path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the store DB in WAL mode for concurrent readers."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    _migrate_schema(conn)
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add storage-v3 provenance columns to existing canonical databases."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(candidate_results)")}
    additions = {
        "lane": "TEXT NOT NULL DEFAULT 'model-core'",
        "environment_name": "TEXT",
        "cost_classification": "TEXT NOT NULL DEFAULT 'unavailable'",
        "environment_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE candidate_results ADD COLUMN {name} {declaration}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_results_lane ON candidate_results(lane)")


# ── Ingestion ──────────────────────────────────────────────────────────────


def split_scenario(scenario_id: str) -> tuple[str, str]:
    if "." in scenario_id:
        suite, name = scenario_id.split(".", 1)
        return suite, name
    return scenario_id, scenario_id


def primary_score(scores: list[dict[str, Any]], success: bool) -> dict[str, Any] | None:
    """Pick the score that carries the cell's pass/fail signal (mirrors gb-results)."""
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


def ingest_run(conn: sqlite3.Connection, run_json_path: Path, repo_root: Path) -> tuple[str, int]:
    """Import one run.json (and its on-disk artifacts) into the store.

    Idempotent: re-ingesting a run_id deletes and replaces its rows. Returns
    (run_id, candidate_result_count). Also pulls inline artifacts from the
    run's cell directories so the DB is self-sufficient for click-through.
    """
    with run_json_path.open("r", encoding="utf-8") as f:
        run = json.load(f)

    run_id = run.get("run_id") or run_json_path.parent.name
    _delete_run(conn, run_id)

    results = run.get("results") or []
    scenario_ids = [r.get("scenario_id") or r.get("scenarioId") for r in results]
    suites = sorted({split_scenario(s)[0] for s in scenario_ids if s})
    candidate_ids = {
        cr.get("candidate_id") or cr.get("candidateId")
        for sr in results
        for cr in (sr.get("candidate_results") or sr.get("candidateResults") or [])
    }
    rel_run_dir = os.path.relpath(run_json_path.parent, repo_root)

    conn.execute(
        """
        INSERT INTO runs(run_id, started_at, completed_at, label, run_dir,
                         suites_json, scenario_count, candidate_count, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            run.get("started_at") or run.get("startedAt"),
            run.get("completed_at") or run.get("completedAt"),
            run.get("label"),
            rel_run_dir,
            json.dumps(suites),
            len(results),
            len([c for c in candidate_ids if c]),
            json.dumps(run.get("metadata") or {}),
        ),
    )

    cell_count = 0
    run_dir = run_json_path.parent
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
            environment = _environment_envelope(cr)
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
                    primary_explanation, lane, environment_name, cost_classification,
                    environment_json, failure_categories_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, scenario_id, scenario_version, suite, scenario_name,
                    cr.get("candidate_id") or cr.get("candidateId"),
                    cr.get("candidate_name") or cr.get("candidateName"),
                    cr.get("candidate_kind") or cr.get("candidateKind"),
                    model_identity.get("model"),
                    model_identity.get("provider"),
                    model_identity.get("base_url"),
                    model_identity.get("display_name"),
                    1 if cr.get("success") else 0,
                    cr.get("error"),
                    cr.get("duration_ms") or cr.get("durationMs"),
                    artifact_dir,
                    primary.get("scorer_id") or primary.get("scorerId") if primary else None,
                    primary.get("score") if primary else None,
                    _bool_int(primary.get("passed")) if primary else None,
                    primary.get("human_summary") if primary else None,
                    primary.get("explanation") if primary else None,
                    environment["lane"],
                    environment.get("name"),
                    environment.get("cost", {}).get("classification", "unavailable"),
                    json.dumps(environment),
                    json.dumps(failure_categories),
                ),
            )
            cr_id = cur.lastrowid
            cell_count += 1

            _ingest_scores(conn, cr_id, scores)
            for cat in failure_categories:
                conn.execute(
                    "INSERT OR IGNORE INTO failure_categories(candidate_result_id, category) VALUES (?, ?)",
                    (cr_id, cat),
                )
            # Pull inline artifacts from the cell's on-disk directory.
            cell_dir = _cell_dir_for(run_dir, scenario_id, cr.get("candidate_id") or cr.get("candidateId"))
            if cell_dir:
                _ingest_artifacts(conn, cr_id, run_id, cell_dir, repo_root)
            # Capture code samples from coding scorers (structure/maintainability already compute these).
            _ingest_samples_from_scores(conn, cr_id, scores)

    conn.commit()
    return run_id, cell_count


def _environment_envelope(candidate_result: dict[str, Any]) -> dict[str, Any]:
    value = candidate_result.get("environment")
    if isinstance(value, dict) and value:
        return value
    # Legacy rows predate storage v3. They remain queryable and are explicitly
    # labeled instead of being silently merged with environment-realized runs.
    return {
        "schema_version": "1",
        "lane": "model-core",
        "name": "legacy-unclassified",
        "cost": {"classification": "unavailable", "amount": None, "currency": None, "basis": None},
    }


def _ingest_scores(conn: sqlite3.Connection, cr_id: int, scores: list[dict[str, Any]]) -> None:
    for score in scores:
        conn.execute(
            """
            INSERT INTO scores(
                candidate_result_id, scorer_id, scorer_name, scoring_kind, success,
                error, score, passed, threshold, explanation, human_summary,
                judge_model, judge_prompt_version, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cr_id,
                score.get("scorer_id") or score.get("scorerId"),
                score.get("scorer_name") or score.get("scorerName"),
                score.get("scoring_kind") or score.get("scoringKind"),
                1 if score.get("success") else 0,
                score.get("error"),
                score.get("score"),
                _bool_int(score.get("passed")),
                score.get("threshold"),
                score.get("explanation"),
                score.get("human_summary"),
                score.get("judge_model") or score.get("judgeModel"),
                score.get("judge_prompt_version") or score.get("judgePromptVersion"),
                json.dumps(score.get("detail") or {}),
            ),
        )


def _ingest_artifacts(
    conn: sqlite3.Connection, cr_id: int, run_id: str, cell_dir: Path, repo_root: Path
) -> None:
    """Inline artifacts under INLINE_MAX_BYTES; reference larger ones by path."""
    if not cell_dir.is_dir():
        return
    for name, mime in INLINE_ARTIFACT_NAMES.items():
        path = cell_dir / name
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        content_bytes: bytes | None = None
        external_path: str | None = None
        if size <= INLINE_MAX_BYTES:
            try:
                content_bytes = path.read_bytes()
            except OSError:
                content_bytes = None
                external_path = _rel(path, repo_root)
        else:
            external_path = _rel(path, repo_root)
        conn.execute(
            """
            INSERT OR REPLACE INTO artifacts(
                candidate_result_id, run_id, name, mime, size_bytes, content_bytes, external_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cr_id, run_id, name, mime, size, content_bytes, external_path),
        )


def _ingest_samples_from_scores(
    conn: sqlite3.Connection, cr_id: int, scores: list[dict[str, Any]]
) -> None:
    """Extract representative code samples from coding-scorer detail.

    The structure/maintainability scorers emit aggregate metrics; the *useful*
    per-cell data for a human is "which files changed and by how much" (from
    maintainability-metrics.deltas) plus the changed-code excerpt itself.
    We capture a compact summary per changed file so the report tool can show
    "here's the code this model touched" without re-reading raw artifacts.
    """
    changed_files: list[str] = []
    line_deltas: dict[str, int] = {}
    summary_bits: dict[str, Any] = {}
    for score in scores:
        sid = score.get("scorer_id") or score.get("scorerId") or ""
        detail = score.get("detail") or {}
        if sid == "maintainability-metrics":
            deltas = detail.get("deltas") or {}
            cf = deltas.get("changed_files") or []
            if isinstance(cf, list):
                changed_files = [str(f) for f in cf if isinstance(f, str)]
            ld = deltas.get("line_deltas") or {}
            if isinstance(ld, dict):
                line_deltas = {str(k): int(v) for k, v in ld.items() if isinstance(v, (int, float))}
            cur = detail.get("current") or {}
            if isinstance(cur, dict):
                summary_bits.update(cur)
        elif sid == "structure-metrics":
            for k in ("total_functions", "lines_per_function", "docstring_coverage",
                      "type_annotation_depth", "test_to_source_ratio"):
                if k in detail:
                    summary_bits[k] = detail[k]

    # One overall summary sample (aggregate metrics, human-readable).
    if summary_bits:
        conn.execute(
            "INSERT OR IGNORE INTO representative_samples"
            "(candidate_result_id, kind, label, language, content, source_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cr_id, "metrics_summary", "summary", "python",
             json.dumps(summary_bits, indent=2), None),
        )

    # One sample per changed file (path + LOC delta). The actual file contents
    # are available via the inlined agent.patch artifact for click-through.
    for path in changed_files:
        delta = line_deltas.get(path, 0)
        conn.execute(
            "INSERT OR IGNORE INTO representative_samples"
            "(candidate_result_id, kind, label, language, content, source_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cr_id, "changed_file", path, "python",
             f"{path}: +{delta} line(s) changed\n(see agent.patch artifact for the full diff)",
             path),
        )


def _cell_dir_for(run_dir: Path, scenario_id: str, candidate_id: str | None) -> Path | None:
    if not candidate_id:
        return None
    # Match the RunContext layout: scenarios/<sid>/candidates/<cid>/.
    return run_dir / "scenarios" / scenario_id / "candidates" / candidate_id


def _delete_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))


def _bool_int(v: Any) -> int | None:
    if v is None:
        return None
    return 1 if v else 0


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return os.path.relpath(path, repo_root)
    except ValueError:
        return str(path)


# ── Ring buffer: prune old run files (DB rows are never pruned here) ───────


def prune_run_files(runs_root: Path, keep: int) -> list[str]:
    """Keep only the ``keep`` most recent run-* dirs; delete the rest from disk.

    Returns the list of pruned run_ids. The DB rows for those runs are NOT
    touched — the DB is canonical and retains full history. Only the scratch
    files (which are regenerable by re-running) are pruned.
    """
    if keep < 0:
        return []
    run_dirs = sorted(
        (p for p in runs_root.glob("run-*") if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    pruned: list[str] = []
    import shutil
    for d in run_dirs[keep:]:
        try:
            shutil.rmtree(d)
            pruned.append(d.name)
        except OSError:
            pass
    return pruned


def ingest_all(conn: sqlite3.Connection, runs_root: Path, repo_root: Path) -> tuple[int, int]:
    """Import every run-*/run.json under runs_root. Returns (runs, cells)."""
    paths = sorted(p for p in runs_root.glob("run-*/run.json") if p.is_file())
    runs = cells = 0
    for p in paths:
        try:
            _, c = ingest_run(conn, p, repo_root)
            runs += 1
            cells += c
        except Exception as ex:  # noqa: BLE001 — one bad run shouldn't abort the rest
            import sys
            print(f"Warning: failed to ingest {p}: {ex}", file=sys.stderr)
    return runs, cells
