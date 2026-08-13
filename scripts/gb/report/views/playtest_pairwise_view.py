"""Relational report for interactive playtest cells.

The view intentionally has no score column.  It renders the pair label and
the retained evidence pointers so a human can inspect a disputed result.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
from typing import Any

from . import ViewContext, ViewResult, register
from ..envelope import esc


def render(ctx: ViewContext) -> ViewResult:
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"members": [], "outcome": "invalid_pair"})
    for cell in ctx.cells:
        score_rows = ctx.conn.execute(
            "SELECT detail_json FROM scores WHERE candidate_result_id=? AND scorer_id=? ORDER BY id DESC LIMIT 1",
            (cell["id"], "playtest-evidence"),
        ).fetchall()
        if not score_rows:
            continue
        try:
            detail = json.loads(score_rows[0]["detail_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            detail = {}
        pair_id = str(detail.get("pair_id") or "").strip()
        if not pair_id:
            continue
        group = groups[pair_id]
        group["scenario_id"] = cell.get("scenario_id")
        group["defect_family"] = detail.get("defect_family") or group.get("defect_family") or "unclassified"
        group["campaign_id"] = detail.get("campaign_id") or group.get("campaign_id") or "unlabeled"
        group["repetition"] = detail.get("repetition") if detail.get("repetition") is not None else group.get("repetition", 0)
        group["outcome"] = detail.get("pair_outcome") or group.get("outcome") or "invalid_pair"
        decision = detail.get("pair_decision") if isinstance(detail.get("pair_decision"), dict) else {}
        group["reason"] = decision.get("reason") or group.get("reason") or ""
        group["members"].append({
            "candidate_id": cell.get("candidate_id") or "?",
            "candidate_name": cell.get("candidate_name") or cell.get("candidate_id") or "?",
            "role": detail.get("pair_role") or "?",
            "model": cell.get("model") or "?",
            "provider": cell.get("provider") or "?",
            "behavioral_status": detail.get("behavioral_status") or "?",
            "defect_family_claim": detail.get("defect_family_claim") or "unstructured/no claim",
            "evidence_valid": detail.get("evidence_valid"),
            "evidence_index": detail.get("evidence_index") or "",
            "archive": _archive_path(detail),
            "finish_outcome": detail.get("finish_outcome") or "?",
            "observation_count": detail.get("observation_count"),
            "frame_count": detail.get("frame_count"),
            "actions_used": detail.get("actions_used"),
            "errors": detail.get("errors") or [],
            "duration_ms": cell.get("duration_ms"),
            "cost": _environment_cost(cell),
            "cleanup": _cleanup_summary(detail, cell),
        })

    if not groups:
        return ViewResult(
            title="Interactive playtest pairwise (no data)",
            html="<p>No pairwise playtest cells matched the filters.</p>",
        )

    rows: list[str] = []
    for pair_id, group in sorted(groups.items()):
        members = sorted(group["members"], key=lambda member: (member["role"], member["candidate_id"]))
        member_html = "<br>".join(
            f"<b>{esc(member['role'])}</b> {esc(member['candidate_name'])} — "
            f"model={esc(member['model'])}, provider={esc(member['provider'])}; "
            f"{esc(member['behavioral_status'])}; terminal={esc(member['finish_outcome'])}; "
            f"claim={esc(member['defect_family_claim'])}; "
            f"evidence {'valid' if member['evidence_valid'] else 'invalid'}; "
            f"actions={esc(str(member['actions_used'] if member['actions_used'] is not None else '—'))}, "
            f"observations={esc(str(member['observation_count'] if member['observation_count'] is not None else '—'))}, "
            f"frames={esc(str(member['frame_count'] if member['frame_count'] is not None else '—'))}, "
            f"elapsed={esc(str(member['duration_ms'] if member['duration_ms'] is not None else '—'))}ms, "
            f"cost={esc(member['cost'])}, cleanup={esc(member['cleanup'])}"
            + (f"<br>{_evidence_link(member['archive'], member['evidence_index'])}" if (member['archive'] or member['evidence_index']) else "")
            + (f"<br><span class='muted'>warnings/errors: {esc('; '.join(member['errors']))}</span>" if member['errors'] else "")
            for member in members
        )
        outcome = str(group.get("outcome") or "invalid_pair")
        css = "pass" if outcome in {"challenger_win", "luna_win", "tie"} else "fail"
        rows.append(
            f"<tr><td><code>{esc(pair_id)}</code><br><span class='muted'>{esc(group.get('scenario_id') or '')}</span><br><span class='muted'>campaign: {esc(group.get('campaign_id') or 'unlabeled')} · repetition: {esc(str(group.get('repetition', 0)))}</span><br><span class='muted'>family: {esc(group.get('defect_family') or 'unclassified')}</span><br><span class='muted'>reason: {esc(group.get('reason') or 'not recorded')}</span></td>"
            f"<td class='{css}'><b>{esc(outcome)}</b></td><td>{member_html}</td></tr>"
        )
    outcome_counts: dict[str, int] = defaultdict(int)
    for group in groups.values():
        outcome_counts[str(group.get("outcome") or "invalid_pair")] += 1
    counts_html = " · ".join(
        f"<b>{esc(label)}</b> {count}" for label, count in (
            ("challenger_win", outcome_counts.get("challenger_win", 0)),
            ("luna_win", outcome_counts.get("luna_win", 0)),
            ("tie", outcome_counts.get("tie", 0)),
            ("invalid_pair", outcome_counts.get("invalid_pair", 0)),
        )
    )
    html = (
        "<h2>Relational incumbent versus challenger outcomes</h2>"
        f"<p class='muted'>Pair counts: {counts_html}</p>"
        "<p class='muted'>No abstract strength score is shown. A tie means this corpus did not distinguish the two cells; invalid_pair means the evidence or pairing contract was not comparable.</p>"
        "<table><thead><tr><th>pair</th><th>outcome</th><th>matched cells and evidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return ViewResult(title="Interactive playtest pairwise", html=html)


def _archive_path(detail: dict[str, Any]) -> str:
    archive = detail.get("evidence_archive")
    if isinstance(archive, dict):
        return str(archive.get("archive_dir") or "")
    return ""


def _evidence_link(archive: str, index: str) -> str:
    """Render a local, durable evidence pointer without embedding large media."""

    if archive:
        target = Path(archive) / "playtest-index.json"
        label = f"archive index: {target}"
    else:
        target = Path(index)
        label = f"evidence index: {target}"
    if target.is_absolute():
        return f"<a href='{esc(target.as_uri())}'>{esc(label)}</a>"
    return f"<span class='muted'>{esc(label)}</span>"


def _environment_cost(cell: dict[str, Any]) -> str:
    try:
        value = json.loads(cell.get("environment_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return str((value.get("cost") or {}).get("classification") or cell.get("cost_classification") or "unavailable")


def _environment_cleanup(cell: dict[str, Any]) -> str:
    try:
        value = json.loads(cell.get("environment_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    cleanup = value.get("cleanup") or {}
    return str(cleanup.get("status") or "not-recorded")


def _cleanup_summary(detail: dict[str, Any], cell: dict[str, Any]) -> str:
    cleanup = detail.get("cleanup")
    if isinstance(cleanup, dict) and cleanup:
        browser = cleanup.get("browser_closed") is True
        driver = cleanup.get("driver_stopped") is True
        return f"browser={'closed' if browser else 'open'}, driver={'stopped' if driver else 'running'}"
    return _environment_cleanup(cell)


register(
    "playtest-pairwise",
    "Playtest pairwise",
    "Relational incumbent/challenger evidence outcomes without a scalar strength score",
    render,
)
