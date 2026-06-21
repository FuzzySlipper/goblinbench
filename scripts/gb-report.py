#!/usr/bin/env python3
"""gb-report — assemble a static HTML report from the GoblinBench store.

LLM-friendly CLI: stable, chainable parameters, self-documenting via --help.
The tool owns DB access + view dispatch + HTML writing; the caller (often an
LLM) decides what to report and supplies the narrative prose.

Examples:

  # Compare models across all recent runs in a suite
  gb-report --suite coding --view grid --out coding-grid.html

  # Failure triage for one run
  gb-report --runs run-20260620-181123-a9845625 --view failures \\
    --narrative "glm52 regressed on maintainability — see below" --out failures.html

  # Deep-dive one cell (model × scenario)
  gb-report --model glm52 --scenario coding.maintainability-mini-service-python --view cell --out cell.html

  # Narrative piped via stdin
  gb-report --suite orchestrator --view grid --narrative - --out grid.html < narrative.md
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gb.report import get_views, render_page  # noqa: E402
from gb.report.views import ViewContext  # noqa: E402
from gb.store import DbPaths, open_db  # noqa: E402


def build_filters(args: argparse.Namespace) -> tuple[str, list]:
    """Translate CLI filters into a SQL WHERE clause + params."""
    where: list[str] = []
    params: list = []
    if args.runs:
        ids = [r.strip() for r in args.runs.split(",") if r.strip()]
        where.append(f"cr.run_id IN ({','.join('?'*len(ids))})")
        params.extend(ids)
    if args.suite:
        where.append("cr.suite = ?")
        params.append(args.suite)
    if args.scenario:
        where.append("cr.scenario_id = ?")
        params.append(args.scenario)
    if args.model:
        where.append("(cr.model = ? OR cr.candidate_id = ?)")
        params.extend([args.model, args.model])
    if args.provider:
        where.append("cr.provider = ?")
        params.append(args.provider)
    if args.passing_only:
        where.append("cr.primary_passed = 1")
    if args.failing_only:
        where.append("(cr.primary_passed = 0 OR cr.primary_passed IS NULL)")
    return (" WHERE " + " AND ".join(where)) if where else "", params


def fetch_cells(conn, args: argparse.Namespace) -> list[dict]:
    where_sql, params = build_filters(args)
    sql = f"""
        SELECT cr.id, cr.run_id, cr.scenario_id, cr.scenario_version, cr.suite, cr.scenario_name,
               cr.candidate_id, cr.candidate_name, cr.candidate_kind, cr.model, cr.provider,
               cr.base_url, cr.display_name, cr.success, cr.error, cr.duration_ms,
               cr.artifact_directory, cr.primary_scorer_id, cr.primary_score, cr.primary_passed,
               cr.primary_summary, cr.primary_explanation, cr.failure_categories_json
        FROM candidate_results cr
        {where_sql}
        ORDER BY cr.run_id DESC, cr.suite, cr.scenario_id, cr.model
        LIMIT ?
    """
    params.append(args.limit)
    return [dict(r) for r in conn.execute(sql, params)]


def resolve_narrative(args: argparse.Namespace) -> str:
    if args.narrative is None:
        return ""
    if args.narrative == "-":
        return sys.stdin.read()
    return args.narrative


def resolve_out_path(args: argparse.Namespace, view_id: str, cells: list[dict]) -> Path:
    if args.out:
        return Path(args.out)
    # Default: runs/<run-id-or-"report">/<view>.html, or runs/<view>.html for multi-run.
    runs_root = DbPaths.resolve().runs_root
    if len(cells) == 1 or args.runs and "," not in args.runs:
        run_id = (cells[0]["run_id"] if cells else (args.runs or "report"))
        return runs_root / run_id / f"{view_id}.html"
    return runs_root / f"{view_id}.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gb-report",
        description="Assemble a static HTML report from the GoblinBench store.",
        epilog="Views: " + ", ".join(f"{v['id']} ({v['name']})" for v in get_views().values()),
    )
    # Data filters
    parser.add_argument("--runs", help="comma-separated run_id list")
    parser.add_argument("--suite")
    parser.add_argument("--scenario")
    parser.add_argument("--model", help="model OR candidate_id")
    parser.add_argument("--provider")
    parser.add_argument("--passing-only", action="store_true")
    parser.add_argument("--failing-only", action="store_true")
    parser.add_argument("--limit", type=int, default=500, help="max cells (default 500)")
    # View + rendering
    parser.add_argument("--view", default="grid", choices=list(get_views()),
                        help="report shape (default grid)")
    parser.add_argument("--embed", default="patch", choices=("patch", "stdout", "output", "none"),
                        help="what artifacts to inline in click-through (default patch)")
    parser.add_argument("--narrative", help="prose lede (text, or '-' for stdin)")
    parser.add_argument("--title", help="report title (default: view name + scope)")
    parser.add_argument("--out", help="output path (default: runs/<run>/<view>.html)")
    parser.add_argument("--open", action="store_true", help="open in default browser after writing")
    args = parser.parse_args(argv)

    paths = DbPaths.resolve()
    if not paths.db_path.exists():
        print(f"Error: store DB not found at {paths.db_path}. Run a benchmark first.", file=sys.stderr)
        return 1
    conn = open_db(paths.db_path)
    cells = fetch_cells(conn, args)
    if not cells:
        print("No cells matched the filters.", file=sys.stderr)
        return 1

    view = get_views()[args.view]
    ctx = ViewContext(
        conn=conn, cells=cells,
        filters={k: v for k, v in vars(args).items()
                 if k in ("runs", "suite", "scenario", "model", "provider") and v},
        repo_root=str(paths.repo_root),
        embed=args.embed,
    )
    result = view["render"](ctx)
    conn.close()

    narrative = resolve_narrative(args)
    title = args.title or result.title
    page = render_page(
        title=title,
        scope={k: str(v) for k, v in ctx.filters.items()},
        narrative=narrative,
        view_html=result.html,
        footnotes=result.footnotes,
        generated_by=f"gb-report --view {args.view}",
    )

    out_path = resolve_out_path(args, args.view, cells)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    print(f"Wrote {out_path} ({len(page):,} bytes, {len(cells)} cell(s), view={args.view})")
    if args.open:
        import webbrowser
        webbrowser.open(out_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
