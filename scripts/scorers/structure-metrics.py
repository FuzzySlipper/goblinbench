#!/usr/bin/env python3
"""
Structure-metrics scorer script for the GoblinBench scoring pipeline.

Emits a score contract JSON that the pipeline consumes.

Usage (via gb-score.py):
  python3 scripts/scorers/structure-metrics.py --fixture-dir <path>

Standalone:
  python3 scripts/scorers/structure-metrics.py --fixture-dir <path> [--artifact-dir <path>]
"""

import argparse
import importlib.util
import json
import os
import pathlib
import sys

# Import structure-metrics (hyphenated filename — use importlib)
SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "structure_metrics",
    SCRIPT_DIR / "structure-metrics.py",
)
if spec is None or spec.loader is None:
    print("ERROR: could not import scripts/structure-metrics.py", file=sys.stderr)
    sys.exit(1)
struct_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(struct_mod)
run_metrics = struct_mod.run_metrics


def main():
    parser = argparse.ArgumentParser(description="Structure metrics scorer")
    parser.add_argument("--fixture-dir", required=True,
                        help="Fixture directory to analyze")
    parser.add_argument("--artifact-dir", help="Directory for score artifacts (optional)")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="Pass/fail threshold (unused — metrics are non-binary)")
    parser.add_argument("--params", help="JSON-encoded scenario parameters (optional)")
    args = parser.parse_args()

    fixture_dir = args.fixture_dir

    if not os.path.isdir(fixture_dir):
        print(json.dumps({
            "scorer_id": "structure-metrics",
            "scorer_name": "Structure Metrics",
            "scoring_kind": "script",
            "success": False,
            "error": f"Fixture directory not found: {fixture_dir}",
            "human_summary": "FAIL: structure-metrics: fixture not found",
        }))
        sys.exit(0)

    try:
        metrics = run_metrics(fixture_dir)
    except Exception as ex:
        print(json.dumps({
            "scorer_id": "structure-metrics",
            "scorer_name": "Structure Metrics",
            "scoring_kind": "script",
            "success": False,
            "error": str(ex),
            "human_summary": f"FAIL: structure-metrics: {ex}",
        }))
        sys.exit(0)

    # Build summary from key metrics
    lpf = metrics.get("lines_per_function", {})
    summary_parts = [
        f"{metrics.get('total_impl_files', 0)} impl files",
        f"{metrics.get('total_functions', 0)} functions",
        f"mean {lpf.get('mean', 0)} LOC/fn",
        f"type-depth {metrics.get('type_annotation_depth', 0):.0%}",
        f"docstring {metrics.get('docstring_coverage', 0):.0%}",
        f"test:source {metrics.get('test_to_source_ratio', 0):.2f}",
    ]

    result = {
        "scorer_id": "structure-metrics",
        "scorer_name": "Structure Metrics",
        "scoring_kind": "script",
        "success": True,
        "score": 1.0,  # Non-binary — always 1.0, the detail carries the signal
        "passed": True,
        "human_summary": ", ".join(summary_parts),
        "explanation": "Structural analysis of implementation files.",
        "detail": metrics,
    }

    print(json.dumps(result))

    # Optionally write metrics to artifact dir
    if args.artifact_dir:
        os.makedirs(args.artifact_dir, exist_ok=True)
        with open(os.path.join(args.artifact_dir, "structure-metrics.json"), "w") as f:
            json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()
