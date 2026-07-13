"""Compact environment-realized comparison table."""

from __future__ import annotations

from typing import Any

from . import ViewContext, ViewResult, environment_for_cell, register
from ..envelope import esc


def render(ctx: ViewContext) -> ViewResult:
    rows = [_row(cell) for cell in ctx.cells]
    html = """
<h2>Environment comparison</h2>
<table><thead><tr>
<th>lane</th><th>environment/profile</th><th>model</th><th>scenario</th>
<th>outcome</th><th class="num">elapsed</th><th>usage</th><th>cost basis</th>
</tr></thead><tbody>""" + "".join(rows) + """</tbody></table>
<p class="muted">Rows remain environment-scoped; model-core and environment-realized results are never aggregated together.</p>
"""
    return ViewResult(title="Environment comparison", html=html)


def _row(cell: dict[str, Any]) -> str:
    env = environment_for_cell(cell)
    profile = env.get("profile") or {}
    usage = env.get("usage") or {}
    cost = env.get("cost") or {}
    passed = cell.get("primary_passed")
    outcome = "PASS" if passed else ("FAIL" if passed == 0 else "—")
    score = cell.get("primary_score")
    if score is not None:
        outcome += f" {score:.2f}"
    usage_text = _usage(usage)
    cost_text = str(cost.get("classification") or "unavailable")
    if cost.get("amount") is not None:
        cost_text += f" {cost.get('amount')} {cost.get('currency') or ''}".rstrip()
    env_text = str(env.get("name") or "?")
    if profile.get("id"):
        env_text += f" / {profile['id']}"
    return (
        f"<tr><td>{esc(env.get('lane'))}</td><td>{esc(env_text)}</td>"
        f"<td>{esc(cell.get('model') or cell.get('candidate_id') or '?')}</td>"
        f"<td>{esc(cell.get('scenario_id') or '?')}</td><td>{esc(outcome)}</td>"
        f"<td class='num'>{(cell.get('duration_ms') or 0):,}ms</td>"
        f"<td>{esc(usage_text)}</td><td>{esc(cost_text)}</td></tr>"
    )


def _usage(usage: dict[str, Any]) -> str:
    total = usage.get("total_tokens")
    if total is None:
        return "unavailable"
    pieces = [f"{total:,} total"]
    if usage.get("input_tokens") is not None:
        pieces.append(f"{usage['input_tokens']:,} in")
    if usage.get("output_tokens") is not None:
        pieces.append(f"{usage['output_tokens']:,} out")
    return ", ".join(pieces)


register("environment", "Environment", "Lane-aware environment/model comparison", render)
