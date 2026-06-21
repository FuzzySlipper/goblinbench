"""grid view — model × scenario pass/score matrix.

The workhorse view for "compare models across a variety of test results": one
row per model/candidate, one column per scenario, cells colored by pass/fail
with the score and a click-through <details> for that cell's score breakdown +
embedded artifacts (patch/output) if present.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import ViewContext, ViewResult, fetch_artifact_bytes, fetch_samples, register
from ..envelope import esc


def render(ctx: ViewContext) -> ViewResult:
    cells = ctx.cells
    if not cells:
        return ViewResult(title="Grid (no data)", html="<p>No cells matched the filters.</p>")

    # Group: model → scenario → cell.
    models: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    scenarios_seen: list[str] = []
    seen_scen: set[str] = set()
    for c in cells:
        model = c.get("model") or c.get("candidate_id") or "?"
        sid = c.get("scenario_id") or "?"
        models[model][sid] = c
        if sid not in seen_scen:
            seen_scen.add(sid)
            scenarios_seen.append(sid)

    # Header: model + aggregate + one column per scenario.
    scen_headers = "".join(f"<th>{esc(_short_scenario(s))}</th>" for s in scenarios_seen)
    rows: list[str] = []
    for model in sorted(models, key=lambda m: _model_sort_key(models[m])):
        model_cells = models[model]
        total = len(model_cells)
        passed = sum(1 for c in model_cells.values() if (c.get("primary_passed") or 0))
        rate = f"{100*passed/total:.0f}%" if total else "—"
        scen_cells = "".join(_render_grid_cell(ctx, model_cells.get(s)) for s in scenarios_seen)
        rows.append(
            f"<tr><td><b>{esc(model)}</b><br><span class='muted'>{esc(model_cells[next(iter(model_cells))].get('provider') or '')}</span></td>"
            f"<td class='num'><b>{rate}</b><br><span class='muted'>{passed}/{total}</span></td>"
            f"{scen_cells}</tr>"
        )

    html = f"""
<h2>Model × scenario grid</h2>
<table>
<thead><tr><th>model</th><th class="num">pass</th>{scen_headers}</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<p class="muted">Click a cell for score breakdown and embedded artifacts. Green = pass, red = fail, — = no result.</p>
"""
    return ViewResult(title="Grid comparison", html=html)


def _render_grid_cell(ctx: ViewContext, cell: dict[str, Any] | None) -> str:
    if cell is None:
        return "<td class='muted'>—</td>"
    passed = cell.get("primary_passed")
    score = cell.get("primary_score")
    cls = "pass" if passed else "fail"
    score_str = f"{score:.2f}" if score is not None else "?"
    marker = "✓" if passed else "✗"
    cr_id = cell["id"]
    detail = _render_cell_details(ctx, cell)
    return (
        f"<td class='{cls}'>"
        f"<details><summary>{marker} {score_str}</summary>"
        f"<div class='cell-detail'>{detail}</div></details>"
        f"</td>"
    )


def _render_cell_details(ctx: ViewContext, cell: dict[str, Any]) -> str:
    cr_id = cell["id"]
    parts: list[str] = []
    summary = cell.get("primary_summary") or cell.get("error") or "(no summary)"
    parts.append(f"<div class='muted'>{esc(summary)}</div>")
    if cell.get("failure_categories_json"):
        import json
        cats = json.loads(cell["failure_categories_json"])
        if cats:
            parts.append(f"<div class='cats'>categories: {esc(', '.join(cats))}</div>")

    # All scorer rows (compact).
    scorer_rows = [dict(r) for r in ctx.conn.execute(
        "SELECT scorer_id, score, passed, human_summary FROM scores WHERE candidate_result_id=? ORDER BY id",
        (cr_id,),
    )]
    if scorer_rows:
        body = "".join(
            _scorer_row_html(r) for r in scorer_rows
        )
        parts.append(
            "<table><thead><tr><th>scorer</th><th class='num'>score</th><th>pass</th><th>summary</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    # Embedded artifacts (the click-through payoff).
    if ctx.embed != "none":
        parts.append(_render_embedded_artifacts(ctx, cr_id))

    # Representative samples (code the model produced).
    samples = fetch_samples(ctx, cr_id)
    if samples:
        parts.append(_render_samples(samples))

    return "".join(parts)


def _render_embedded_artifacts(ctx: ViewContext, cr_id: int) -> str:
    names = {
        "patch": "patch", "agent.patch": "patch",
        "output.json": "output.json", "stdout.log": "stdout.log",
    }
    if ctx.embed == "stdout":
        names = {"stdout.log": "stdout.log", "stderr.log": "stderr.log"}
    elif ctx.embed == "output":
        names = {"output.json": "output.json"}
    parts: list[str] = []
    for name, label in names.items():
        data = fetch_artifact_bytes(ctx, cr_id, name)
        if data is None:
            continue
        text = data.decode("utf-8", errors="replace")
        if len(text) > 20000:
            text = text[:20000] + f"\n… ({len(text)} chars total, truncated)"
        parts.append(
            f"<details><summary>{esc(label)}</summary><pre>{esc(text)}</pre></details>"
        )
    return "".join(parts)


def _render_samples(samples: list[dict[str, Any]]) -> str:
    parts = ["<details open><summary>Representative samples</summary>"]
    for s in samples:
        parts.append(
            f"<div class='sample'><div class='sample-label'>{esc(s['kind'])}: {esc(s['label'])}</div>"
            f"<pre>{esc(s['content'])}</pre></div>"
        )
    parts.append("</details>")
    return "".join(parts)


def _short_scenario(sid: str) -> str:
    # "coding.retry-policy" → "retry-policy" (suite shown in a separate column would be cleaner,
    # but short names keep the grid readable when there are many scenarios).
    return sid.split(".", 1)[1] if "." in sid else sid


def _scorer_row_html(r: dict[str, Any]) -> str:
    score = r.get("score")
    score_str = f"{score:.2f}" if score is not None else "—"
    passed = r.get("passed")
    mark = "✓" if passed else ("✗" if passed is not None else "—")
    return (
        f"<tr><td>{esc(r['scorer_id'])}</td><td class='num'>{score_str}</td>"
        f"<td>{mark}</td><td class='muted'>{esc(r.get('human_summary') or '')}</td></tr>"
    )


def _model_sort_key(model_cells: dict[str, dict[str, Any]]) -> tuple[float, str]:
    total = len(model_cells)
    passed = sum(1 for c in model_cells.values() if (c.get("primary_passed") or 0))
    rate = passed / total if total else 0
    return (-rate, "")


register("grid", "Grid", "Model × scenario pass/score matrix (model comparison)", render)
