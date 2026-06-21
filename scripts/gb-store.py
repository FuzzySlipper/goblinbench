#!/usr/bin/env python3
"""GoblinBench store CLI — manual control over the canonical SQLite store.

The store is auto-ingested at the end of every ``gb-run.py`` invocation; this
CLI covers the manual operations:

  import [--reset] [--rebuild]    pull run-*/run.json into the DB
  prune --keep N                  ring-buffer the on-disk run files (DB untouched)
  status                          show DB row counts + on-disk run count + size
  vacuum                          SQLite VACUUM (compact after large deletions)
  artifact <cr-id> <name>         dump one inline artifact to stdout (debug)

The DB (runs/goblinbench.sqlite) is canonical. On-disk run files are scratch
space bounded by the ring buffer. See docs/results-cli.md and
docs/python-runner.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gb.store import (  # noqa: E402
    DbPaths,
    ingest_all,
    ingest_run,
    open_db,
    prune_run_files,
)


def cmd_import(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    conn = open_db(paths.db_path)
    try:
        if args.reset:
            conn.executescript(
                "DELETE FROM representative_samples; DELETE FROM artifacts; "
                "DELETE FROM failure_categories; DELETE FROM scores; "
                "DELETE FROM candidate_results; DELETE FROM run_set_runs; "
                "DELETE FROM run_sets; DELETE FROM runs;"
            )
            conn.commit()
        if args.run_json:
            run_id, cells = ingest_run(conn, Path(args.run_json).resolve(), paths.repo_root)
            print(f"Imported {run_id}: {cells} candidate result(s).")
        else:
            runs, cells = ingest_all(conn, paths.runs_root, paths.repo_root)
            print(f"Imported {runs} run(s), {cells} candidate result(s).")
    finally:
        conn.close()
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    pruned = prune_run_files(paths.runs_root, args.keep)
    print(f"Pruned {len(pruned)} run dir(s) from disk (kept {args.keep} most recent).")
    if pruned and args.verbose:
        for rid in pruned:
            print(f"  {rid}")
    print("DB history is unaffected — re-run a scenario anytime to regenerate files.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    db_exists = paths.db_path.exists()
    db_size = paths.db_path.stat().st_size if db_exists else 0
    on_disk = len([p for p in paths.runs_root.glob("run-*") if p.is_dir()]) if paths.runs_root.exists() else 0
    print(f"DB: {paths.db_path}  ({db_size:,} bytes{'  [missing]' if not db_exists else ''})")
    print(f"Runs root: {paths.runs_root}  ({on_disk} run dir(s) on disk)")
    if not db_exists:
        return 0
    conn = open_db(paths.db_path)
    try:
        for table in ("runs", "candidate_results", "scores", "artifacts",
                      "representative_samples", "failure_categories", "run_sets"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:24s} {n:>8,}")
        # latest run + size-tier breakdown
        row = conn.execute("SELECT run_id, started_at FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if row:
            print(f"  latest run: {row['run_id']}  ({row['started_at']})")
        inlined = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM artifacts WHERE content_bytes IS NOT NULL"
        ).fetchone()
        external = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE content_bytes IS NULL"
        ).fetchone()[0]
        print(f"  artifacts: {inlined[0]} inlined ({inlined[1]:,} bytes), {external} external (size-tiered)")
    finally:
        conn.close()
    return 0


def cmd_vacuum(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    before = paths.db_path.stat().st_size if paths.db_path.exists() else 0
    conn = open_db(paths.db_path)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    after = paths.db_path.stat().st_size
    print(f"VACUUM: {before:,} → {after:,} bytes ({before - after:+,})")
    return 0


def cmd_artifact(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    conn = open_db(paths.db_path)
    try:
        row = conn.execute(
            "SELECT content_bytes, external_path, mime, size_bytes FROM artifacts "
            "WHERE candidate_result_id = ? AND name = ?",
            (args.cr_id, args.name),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        print(f"No artifact {args.name!r} for candidate_result_id {args.cr_id}", file=sys.stderr)
        return 1
    if row["content_bytes"] is not None:
        os.write(1, row["content_bytes"])
        return 0
    # External — read from disk.
    if row["external_path"]:
        p = paths.repo_root / row["external_path"]
        if p.is_file():
            os.write(1, p.read_bytes())
            return 0
    print(f"Artifact {args.name!r} is external but its file is missing.", file=sys.stderr)
    return 1


# ── Management: list / get / delete / label ──────────────────────────────


def _parse_age(spec: str) -> str | None:
    """Parse an --older-than spec into an ISO timestamp cutoff. Returns None on failure.

    Supports: '30d', '2w', '12h', '2026-01-31', or a full ISO datetime.
    """
    import re
    from datetime import datetime, timedelta, timezone
    spec = spec.strip()
    m = re.fullmatch(r"(\d+)\s*([dhwy])", spec, re.I)
    if m:
        n = int(m.group(1)); unit = m.group(2).lower()
        delta = {"d": 1, "w": 7, "h": 1 / 24, "y": 365}[unit] * n
        return (datetime.now(timezone.utc) - timedelta(days=delta)).isoformat()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(spec, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _run_filters(args: argparse.Namespace) -> tuple[str, list]:
    """Translate the shared --run-id/--suite/--model/--older-than filters into SQL."""
    where: list[str] = []
    params: list = []
    if getattr(args, "run_id", None):
        ids = [r.strip() for r in args.run_id.split(",") if r.strip()]
        where.append(f"run_id IN ({','.join('?' * len(ids))})")
        params.extend(ids)
    if getattr(args, "suite", None):
        where.append("run_id IN (SELECT DISTINCT run_id FROM candidate_results WHERE suite = ?)")
        params.append(args.suite)
    if getattr(args, "model", None):
        where.append(
            "run_id IN (SELECT DISTINCT run_id FROM candidate_results WHERE model = ? OR candidate_id = ?)"
        )
        params.extend([args.model, args.model])
    if getattr(args, "older_than", None):
        cutoff = _parse_age(args.older_than)
        if cutoff is None:
            raise SystemExit(f"Error: could not parse --older-than {args.older_than!r} "
                             "(try '30d', '2w', or '2026-01-31')")
        where.append("(started_at IS NULL OR started_at < ?)")
        params.append(cutoff)
    return (" WHERE " + " AND ".join(where)) if where else "", params


def cmd_list(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    conn = open_db(paths.db_path)
    try:
        where_sql, params = _run_filters(args)
        # Per-run aggregate: cell count, pass count, suites.
        rows = conn.execute(
            f"""
            SELECT r.run_id, r.started_at, r.label,
                   (SELECT COUNT(*) FROM candidate_results cr WHERE cr.run_id = r.run_id) AS cells,
                   (SELECT COUNT(*) FROM candidate_results cr
                    WHERE cr.run_id = r.run_id AND cr.primary_passed = 1) AS passed,
                   r.suites_json
            FROM runs r
            {where_sql}
            ORDER BY r.started_at DESC
            LIMIT ?
            """,
            params + [args.limit],
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("(no runs match)")
        return 0
    import json
    print(f"{'run_id':40s} {'started':22s} {'pass':>8s}  label")
    print("-" * 100)
    for r in rows:
        suites = ",".join(json.loads(r["suites_json"] or "[]"))
        pass_str = f"{r['passed']}/{r['cells']}" if r["cells"] else "—"
        label = (r["label"] or "")
        if suites:
            label = f"[{suites}] {label}".strip()
        print(f"{r['run_id']:40s} {(r['started_at'] or '?')[:22]:22s} {pass_str:>8s}  {label}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    conn = open_db(paths.db_path)
    try:
        run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (args.run_id,)).fetchone()
        if run is None:
            print(f"Run {args.run_id!r} not found.", file=sys.stderr)
            return 1
        import json
        run = dict(run)
        print(f"run_id: {run['run_id']}")
        print(f"started: {run['started_at']}    completed: {run['completed_at']}")
        print(f"label:   {run['label'] or '(none)'}")
        print(f"suites:  {', '.join(json.loads(run['suites_json'] or '[]'))}")
        print(f"dir:     {run['run_dir']}")
        cells = conn.execute(
            """
            SELECT cr.scenario_id, cr.candidate_id, cr.model, cr.success, cr.primary_passed,
                   cr.primary_score, cr.primary_scorer_id, cr.failure_categories_json
            FROM candidate_results cr WHERE cr.run_id = ?
            ORDER BY cr.scenario_id, cr.candidate_id
            """,
            (args.run_id,),
        ).fetchall()
        print(f"\ncells ({len(cells)}):")
        print(f"  {'scenario':42s} {'candidate':28s} {'pass':>4s} {'score':>6s}  summary")
        for c in cells:
            status = "✓" if c["primary_passed"] else ("✗" if c["primary_passed"] == 0 else "—")
            score = f"{c['primary_score']:.2f}" if c["primary_score"] is not None else "—"
            cats = ",".join(json.loads(c["failure_categories_json"] or "[]"))
            summ = (c["primary_scorer_id"] or "") + (f" ({cats})" if cats else "")
            print(f"  {(c['scenario_id'] or '?'):42s} {(c['candidate_id'] or '?'):28s} {status:>4s} {score:>6s}  {summ}")
    finally:
        conn.close()
    return 0


def _select_runs_for_delete(args: argparse.Namespace, conn) -> list[str]:
    """Resolve the set of run_ids a delete operation would remove. Shared by
    dry-run preview and the actual delete."""
    where_sql, params = _run_filters(args)
    if args.keep_recent is not None:
        # keep-recent overrides the broad filters: keep the N newest, delete the rest.
        # (Still ANDs with explicit filters like --suite if both given.)
        rows = conn.execute(
            f"""
            SELECT run_id FROM (
                SELECT run_id,
                       ROW_NUMBER() OVER (ORDER BY started_at DESC NULLS LAST) AS rn
                FROM runs {where_sql}
            ) WHERE rn > ?
            """,
            params + [args.keep_recent],
        ).fetchall()
        return [r["run_id"] for r in rows]
    if not where_sql:
        return []  # refuse to delete everything without an explicit selector
    return [r["run_id"] for r in conn.execute(f"SELECT run_id FROM runs {where_sql}", params)]


def cmd_delete(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    # Safety model: an explicit --run-id is intentional (you named it) → direct.
    # Any filter (--suite/--model/--older-than/--keep-recent) is emergent — you
    # don't know how many it'll match — so it ALWAYS requires --yes, even for 1
    # match. This prevents "delete --suite X" from silently nuking a lone run.
    explicit_ids = []
    if getattr(args, "run_id", None):
        explicit_ids = [r.strip() for r in args.run_id.split(",") if r.strip()]
    filter_based = any(getattr(args, k, None) for k in ("suite", "model", "older_than")) \
        or args.keep_recent is not None

    conn = open_db(paths.db_path)
    try:
        run_ids = _select_runs_for_delete(args, conn)
    finally:
        conn.close()

    # If the caller named explicit run-ids AND asked to remove files, also pick
    # up any on-disk dirs that are already orphaned (no DB row). Otherwise a
    # run whose DB row was already deleted can't have its files cleaned up
    # through this command — which is exactly when you'd reach for it.
    orphan_file_targets: list[str] = []
    if args.files and explicit_ids:
        orphan_file_targets = [
            rid for rid in explicit_ids
            if rid not in run_ids and (paths.runs_root / rid).is_dir()
        ]

    total = len(run_ids) + len(orphan_file_targets)
    if total == 0:
        print("Nothing matched. (Bulk deletes need an explicit filter; use --run-id, "
              "--suite, --model, --older-than, or --keep-recent.)")
        return 0

    action = "Would delete" if args.dry_run else "Deleting"
    print(f"{action} {len(run_ids)} run(s) from the DB" +
          (f" + {len(orphan_file_targets)} orphaned on-disk dir(s)" if orphan_file_targets else "") + ":")
    for rid in run_ids + orphan_file_targets:
        suffix = " (files only — no DB row)" if rid in orphan_file_targets else ""
        print(f"  {rid}{suffix}")

    # Filter-based deletes require --yes (the count is emergent). Explicit
    # --run-id deletes are direct. --dry-run always previews.
    if filter_based and not args.yes and not args.dry_run:
        print("\nRefusing filter-based delete without --yes (the match count is emergent; "
              "re-run with --yes to proceed, or --dry-run to preview).", file=sys.stderr)
        return 2
    if args.dry_run:
        print("\n(dry-run; no changes made)")
        return 0

    conn = open_db(paths.db_path)
    deleted_files = 0
    try:
        for rid in run_ids:
            conn.execute("DELETE FROM runs WHERE run_id = ?", (rid,))
        conn.commit()
        if args.files:
            import shutil
            for rid in run_ids + orphan_file_targets:
                rd = paths.runs_root / rid
                if rd.is_dir():
                    shutil.rmtree(rd, ignore_errors=True)
                    deleted_files += 1
        if args.vacuum:
            conn.execute("VACUUM")
    finally:
        conn.close()
    parts = [f"Deleted {len(run_ids)} run(s) from the DB."]
    if deleted_files:
        parts.append(f"Removed {deleted_files} on-disk run dir(s).")
    print("\n" + " ".join(parts))
    return 0


def cmd_label(args: argparse.Namespace) -> int:
    paths = DbPaths.resolve()
    conn = open_db(paths.db_path)
    try:
        row = conn.execute("SELECT run_id, label FROM runs WHERE run_id = ?", (args.run_id,)).fetchone()
        if row is None:
            print(f"Run {args.run_id!r} not found.", file=sys.stderr)
            return 1
        if args.label is None:
            print(f"{row['run_id']}: {row['label'] or '(none)'}")
            return 0
        conn.execute("UPDATE runs SET label = ? WHERE run_id = ?", (args.label, args.run_id))
        conn.commit()
        print(f"{args.run_id}: label set to {args.label!r}")
    finally:
        conn.close()
    return 0


def add_run_filter_args(p) -> None:
    """Shared filters for list/delete (the management selectors)."""
    p.add_argument("--run-id", help="comma-separated run_id list")
    p.add_argument("--suite")
    p.add_argument("--model", help="model OR candidate_id")
    p.add_argument("--older-than", help="age cutoff: '30d', '2w', '12h', or '2026-01-31'")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gb-store", description="GoblinBench store control")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="Import run-*/run.json into the DB")
    p_import.add_argument("--reset", action="store_true", help="Clear all rows before importing")
    p_import.add_argument("--run-json", help="Import a single run.json (default: all under runs/)")
    p_import.set_defaults(func=cmd_import)

    p_prune = sub.add_parser("prune", help="Ring-buffer the on-disk run files (DB untouched)")
    p_prune.add_argument("--keep", type=int, default=20, help="Number of recent run dirs to keep")
    p_prune.add_argument("--verbose", action="store_true")
    p_prune.set_defaults(func=cmd_prune)

    p_status = sub.add_parser("status", help="Show DB + on-disk counts and sizes")
    p_status.set_defaults(func=cmd_status)

    p_vacuum = sub.add_parser("vacuum", help="Compact the DB (VACUUM)")
    p_vacuum.set_defaults(func=cmd_vacuum)

    p_art = sub.add_parser("artifact", help="Dump one inline artifact to stdout")
    p_art.add_argument("cr_id", type=int, help="candidate_result_id")
    p_art.add_argument("name", help="artifact name (patch / output.json / scores.json / ...)")
    p_art.set_defaults(func=cmd_artifact)

    # ── Management ──
    p_list = sub.add_parser("list", help="List runs (with optional filters)")
    add_run_filter_args(p_list)
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="Show one run's cells and per-cell pass/fail")
    p_get.add_argument("run_id")
    p_get.set_defaults(func=cmd_get)

    p_del = sub.add_parser("delete", help="Delete run(s) from the DB (and optionally their files)")
    add_run_filter_args(p_del)
    p_del.add_argument("--keep-recent", type=int,
                       help="keep the N most recent, delete the rest (DB-side; complements 'prune')")
    p_del.add_argument("--files", action="store_true",
                       help="also delete the on-disk run dirs (default: DB only)")
    p_del.add_argument("--dry-run", action="store_true", help="preview without deleting (default for bulk)")
    p_del.add_argument("--yes", action="store_true", help="confirm a bulk delete")
    p_del.add_argument("--vacuum", action="store_true", help="VACUUM after deleting")
    p_del.set_defaults(func=cmd_delete)

    p_label = sub.add_parser("label", help="Get or set a run's label")
    p_label.add_argument("run_id")
    p_label.add_argument("label", nargs="?", help="new label (omit to read current)")
    p_label.set_defaults(func=cmd_label)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
