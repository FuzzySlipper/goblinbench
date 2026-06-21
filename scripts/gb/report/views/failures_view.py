"""failures view — failure-first triage list.

Shows only failing cells, grouped by failure category, each with the human
summary, the scorer explanation, and a click-through to the embedded
artifacts. This is the "what broke and why" surface for a run or comparison.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from . import ViewContext, ViewResult, fetch_artifact_bytes, fetch_samples, register
from ..envelope import esc


def render(ctx: ViewContext) -> ViewResult:
    cells = ctx.cells
    failing = [c for c in cells if not (c.get("primary_passed") or c.get("success"))]
    if not failing:
        return ViewResult(
            title="Failures (none)",
            html="<p>No failing cells matched the filters. 🎉</p>",
        )

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in failing:
        cats = json.loads(c.get("failure_categories_json") or "[]")
        if not cats:
            cats = ["uncategorized"]
        for cat in cats:
            by_category[cat].append(c)

    total = len(cells)
    fail_rate = f"{100*len(failing)/total:.0f}%" if total else "—"
    parts = [
        f"<h2>Failures — {len(failing)}/{total} cells ({fail_rate})</h2>",
        f"<p class='muted'>Grouped by failure category. Click a cell for artifacts.</p>",
    ]
    for cat in sorted(by_category):
        group = by_category[cat]
        parts.append(f"<h3>{esc(cat)} <span class='muted'>({len(group)})</span></h3>")
        for c in sorted(group, key=lambda c: (c.get("scenario_id") or "", c.get("model") or "")):
            parts.append(_render_failure_cell(ctx, c))

    return ViewResult(title="Failure triage", html="".join(parts))


def _render_failure_cell(ctx: ViewContext, cell: dict[str, Any]) -> str:
    cr_id = cell["id"]
    model = cell.get("model") or cell.get("candidate_id") or "?"
    sid = cell.get("scenario_id") or "?"
    score = cell.get("primary_score")
    score_str = f"{score:.2f}" if score is not None else "—"
    summary = cell.get("primary_summary") or cell.get("error") or "(no summary)"
    parts = [
        f"<details><summary><b>{esc(model)}</b> @ {esc(sid)} <span class='fail'>({score_str})</span></summary>",
        f"<div class='cell-detail'>",
        f"<div class='muted'>{esc(summary)}</div>",
    ]

    scorer_rows = [dict(r) for r in ctx.conn.execute(
        "SELECT scorer_id, score, passed, explanation, human_summary FROM scores "
        "WHERE candidate_result_id=? AND passed=0 ORDER BY id",
        (cr_id,),
    )]
    if scorer_rows:
        body = "".join(
            f"<tr><td>{esc(r['scorer_id'])}</td><td class='num'>{r['score']:.2f}</td>"
            f"<td>{esc(r['explanation'] or r['human_summary'] or '')}</td></tr>"
            for r in scorer_rows
        )
        parts.append(
            "<table><thead><tr><th>scorer</th><th class='num'>score</th><th>why</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    if ctx.embed != "none":
        for name, label in (("agent.patch", "patch"), ("patch", "patch"), ("output.json", "output.json")):
            data = fetch_artifact_bytes(ctx, cr_id, name)
            if data is None:
                continue
            text = data.decode("utf-8", errors="replace")
            if len(text) > 20000:
                text = text[:20000] + f"\n… ({len(text)} chars total)"
            parts.append(f"<details><summary>{esc(label)}</summary><pre>{esc(text)}</pre></details>")
            break  # one artifact is enough in the failure list

    samples = fetch_samples(ctx, cr_id)
    if samples:
        parts.append("<details><summary>Representative samples</summary>")
        for s in samples[:3]:
            parts.append(
                f"<div class='sample'><div class='sample-label'>{esc(s['kind'])}: {esc(s['label'])}</div>"
                f"<pre>{esc(s['content'])}</pre></div>"
            )
        parts.append("</details>")

    parts.append("</div></details>")
    return "".join(parts)


register("failures", "Failures", "Failure-first triage with categories and click-through", render)
