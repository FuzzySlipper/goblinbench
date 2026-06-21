"""cell view — one cell deep-dive.

Renders a single (model × scenario) result in full: every scorer row, the
complete embedded artifact set (patch + output + stdout), and all
representative samples. This is the "drill into specifics, look at the code"
surface.
"""

from __future__ import annotations

import json
from typing import Any

from . import ViewContext, ViewResult, fetch_artifact_bytes, fetch_samples, register
from ..envelope import esc


def render(ctx: ViewContext) -> ViewResult:
    cells = ctx.cells
    if not cells:
        return ViewResult(title="Cell (not found)", html="<p>No cell matched.</p>")
    # If multiple cells match (e.g. same model across runs), take the latest.
    cell = sorted(cells, key=lambda c: c.get("run_id") or "", reverse=True)[0]
    cr_id = cell["id"]
    model = cell.get("model") or cell.get("candidate_id") or "?"
    sid = cell.get("scenario_id") or "?"
    passed = cell.get("primary_passed")
    score = cell.get("primary_score")
    status = "<span class='pass'>PASS</span>" if passed else "<span class='fail'>FAIL</span>"
    score_str = f"{score:.2f}" if score is not None else "—"

    parts = [
        f"<h2>{esc(model)} <span class='muted'>@</span> {esc(sid)}</h2>",
        f"<div class='scope'>{status} · score {score_str} · run {esc(cell.get('run_id') or '?')} · "
        f"{cell.get('duration_ms') or '?'}ms</div>",
    ]

    if cell.get("error"):
        parts.append(f"<div class='cats'>error: {esc(cell['error'])}</div>")

    # Every scorer row, full detail.
    scorer_rows = [dict(r) for r in ctx.conn.execute(
        "SELECT scorer_id, scorer_name, scoring_kind, score, passed, threshold, "
        "explanation, human_summary, detail_json FROM scores WHERE candidate_result_id=? ORDER BY id",
        (cr_id,),
    )]
    if scorer_rows:
        parts.append("<h3>Scores</h3>")
        for r in scorer_rows:
            parts.append(_render_scorer_row(r))

    # All artifacts the cell produced.
    parts.append("<h3>Artifacts</h3>")
    any_art = False
    for name in ("agent.patch", "patch", "output.json", "stdout.log", "stderr.log", "scores.json", "trace.jsonl"):
        data = fetch_artifact_bytes(ctx, cr_id, name)
        if data is None:
            continue
        any_art = True
        text = data.decode("utf-8", errors="replace")
        truncated = len(text) > 50000
        if truncated:
            text = text[:50000] + f"\n… ({len(text)} chars total, truncated for display)"
        open_attr = " open" if name in ("agent.patch", "patch", "output.json") else ""
        parts.append(f"<details{open_attr}><summary>{esc(name)} ({len(data):,} bytes)</summary><pre>{esc(text)}</pre></details>")
    if not any_art:
        parts.append("<p class='muted'>No artifacts stored for this cell.</p>")

    # Representative samples.
    samples = fetch_samples(ctx, cr_id)
    if samples:
        parts.append("<h3>Representative samples</h3>")
        for s in samples:
            parts.append(
                f"<div class='sample'><div class='sample-label'>{esc(s['kind'])}: {esc(s['label'])}"
                f"{' (' + esc(s['language']) + ')' if s.get('language') else ''}</div>"
                f"<pre>{esc(s['content'])}</pre></div>"
            )

    return ViewResult(title=f"{model} @ {sid}", html="".join(parts))


def _render_scorer_row(row: dict[str, Any]) -> str:
    sid = row["scorer_id"]
    score = row["score"]
    passed = row["passed"]
    status = "✓" if passed else ("✗" if passed is not None else "—")
    score_str = f"{score:.2f}" if score is not None else "—"
    detail = json.loads(row.get("detail_json") or "{}")
    detail_html = ""
    if detail:
        # Render detail as a compact key-value table, skipping huge nested arrays.
        rows = []
        for k, v in detail.items():
            if isinstance(v, (list, dict)):
                compact = json.dumps(v)
                if len(compact) > 300:
                    compact = compact[:300] + "…"
            else:
                compact = str(v)
            rows.append(f"<tr><td>{esc(k)}</td><td>{esc(compact)}</td></tr>")
        if rows:
            detail_html = (
                "<details><summary>detail</summary><table><tbody>"
                + "".join(rows) + "</tbody></table></details>"
            )
    explanation = row.get("explanation") or row.get("human_summary") or ""
    return (
        f"<div class='cell-detail'><b>{esc(sid)}</b> {status} {score_str} "
        f"<span class='muted'>{esc(row.get('scorer_name') or '')}</span>"
        f"<div class='muted'>{esc(explanation)}</div>"
        f"{detail_html}</div>"
    )


register("cell", "Cell", "Deep-dive one cell: all scores + artifacts + samples", render)
