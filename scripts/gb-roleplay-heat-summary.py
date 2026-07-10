#!/usr/bin/env python3
"""Summarize roleplay-heat-boundary scorer details as a flat Markdown table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id_or_dir", help="run id/path, or comma-separated ids/paths")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    run_dirs = [_resolve_run_dir(part.strip()) for part in args.run_id_or_dir.split(",") if part.strip()]
    rows: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        rows.extend(collect_rows(run_dir))
    run_name = ",".join(run_dir.name for run_dir in run_dirs)
    md = render(rows, run_name)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"Wrote {out} ({len(rows)} rows)")
    else:
        print(md)
    return 0


def _resolve_run_dir(value: str) -> Path:
    run_dir = Path(value)
    if not run_dir.exists():
        run_dir = Path("runs") / value
    return run_dir


def collect_rows(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scores_path in sorted(run_dir.glob("scenarios/roleplay-heat-boundary.*/candidates/*/scores.json")):
        scenario = scores_path.parents[2].name
        candidate = scores_path.parents[0].name
        try:
            scores = json.loads(scores_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        heat = next((s for s in scores if s.get("scorer_id") == "roleplay-heat-boundary"), None)
        if not heat:
            continue
        detail = heat.get("detail") or {}
        rows.append({
            "scenario": scenario.replace("roleplay-heat-boundary.", ""),
            "candidate": candidate,
            "target": detail.get("target_tier", ""),
            "produced": detail.get("produced_tier", ""),
            "filter": detail.get("filter_behavior", ""),
            "relation": detail.get("target_relation", ""),
            "user_control": len(detail.get("user_control_hits") or []),
            "words": detail.get("word_count", ""),
            "chars": detail.get("char_count", ""),
        })
    return rows


def render(rows: list[dict[str, Any]], run_name: str) -> str:
    lines = [f"# Roleplay heat-boundary summary — `{run_name}`", ""]
    lines.append("| scenario | candidate | target | produced | filter | relation | user-control hits | words |")
    lines.append("|---|---|---|---|---|---|---:|---:|")
    for r in rows:
        lines.append(
            f"| `{r['scenario']}` | `{r['candidate']}` | {r['target']} | {r['produced']} | "
            f"{r['filter']} | {r['relation']} | {r['user_control']} | {r['words']} |"
        )
    lines.append("")
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_candidate.setdefault(str(r["candidate"]), []).append(r)
    lines.append("## Compact per-candidate dial")
    lines.append("")
    lines.append("| candidate | pg13 | r_soft | nc17 | nc17+agency | notes |")
    lines.append("|---|---|---|---|---|---|")
    wanted = {
        "pg13": "pg13-balcony-kiss-v0",
        "r_soft": "r-soft-bedroom-v0",
        "nc17": "nc17-explicit-consenting-adults-v0",
        "nc17+agency": "nc17-no-user-control-v0",
    }
    for candidate in sorted(by_candidate):
        cells = {label: "" for label in wanted}
        notes: list[str] = []
        for label, scenario in wanted.items():
            row = next((r for r in by_candidate[candidate] if r["scenario"] == scenario), None)
            if row:
                cells[label] = f"{row['produced']} / {row['filter']}"
                if row["user_control"]:
                    notes.append(f"{label}: {row['user_control']} user-control hit(s)")
        lines.append(
            f"| `{candidate}` | {cells['pg13']} | {cells['r_soft']} | {cells['nc17']} | {cells['nc17+agency']} | {'; '.join(notes)} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
