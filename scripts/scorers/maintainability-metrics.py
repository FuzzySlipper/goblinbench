#!/usr/bin/env python3
"""Maintainability metrics scorer wrapper for GoblinBench Python pipeline."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("maintainability_metrics", SCRIPT_DIR / "maintainability-metrics.py")
if spec is None or spec.loader is None:
    print("ERROR: could not import scripts/maintainability-metrics.py", file=sys.stderr)
    sys.exit(1)
metrics_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = metrics_mod
spec.loader.exec_module(metrics_mod)


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintainability metrics scorer")
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument("--params")
    args = parser.parse_args()

    if not os.path.isdir(args.fixture_dir):
        print(json.dumps({
            "scorer_id": "maintainability-metrics",
            "scorer_name": "Maintainability Metrics",
            "scoring_kind": "script",
            "success": False,
            "passed": False,
            "score": 0.0,
            "human_summary": "FAIL: maintainability-metrics: fixture not found",
            "error": f"Fixture directory not found: {args.fixture_dir}",
        }))
        return

    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError:
            params = {}

    try:
        metrics = metrics_mod.run_metrics(
            args.fixture_dir,
            source_root=params.get("source_root", "service"),
            baseline_path=params.get("baseline_path", ".goblinbench/maintainability-baseline.json"),
            central_paths=params.get("central_paths"),
            setup_paths=params.get("setup_paths"),
            handler_paths=params.get("handler_paths"),
        )
    except Exception as ex:
        print(json.dumps({
            "scorer_id": "maintainability-metrics",
            "scorer_name": "Maintainability Metrics",
            "scoring_kind": "script",
            "success": False,
            "passed": False,
            "score": 0.0,
            "human_summary": f"FAIL: maintainability-metrics: {ex}",
            "error": str(ex),
        }))
        return

    deltas = metrics.get("deltas", {})
    current = metrics.get("current", {})
    summary = (
        f"changed {deltas.get('changed_file_count', 0)} files, "
        f"max-change-share {deltas.get('max_changed_file_share', 0):.0%}, "
        f"central-change-share {deltas.get('central_changed_mass_share', 0):.0%}, "
        f"largest-fn Δ {deltas.get('summary_delta', {}).get('largest_function_lines', 0):+}, "
        f"handler max {current.get('max_handler_function_lines', 0)} LOC"
    )

    result = {
        "scorer_id": "maintainability-metrics",
        "scorer_name": "Maintainability Metrics",
        "scoring_kind": "script",
        "success": True,
        "score": 1.0,
        "passed": True,
        "human_summary": summary,
        "explanation": "Architectural maintainability metrics compared to fixture baseline.",
        "detail": metrics,
    }
    print(json.dumps(result))

    if args.artifact_dir:
        os.makedirs(args.artifact_dir, exist_ok=True)
        with open(os.path.join(args.artifact_dir, "maintainability-metrics.json"), "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
