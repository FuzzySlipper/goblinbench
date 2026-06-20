#!/usr/bin/env python3
"""
GoblinBench Scoring Pipeline — language-agnostic post-processing scorer.

Reads a run directory (produced by the .NET runner), discovers scenario
configs, dispatches to per-language Python scorer scripts, and writes
updated scores back to run.json.

Usage:
    python3 scripts/gb-score.py <run-dir>
    python3 scripts/gb-score.py <run-dir> --verbose

The pipeline:
  1. Reads run.json (scenario x candidate results with fixture_dir)
  2. Loads scenario JSONs from suites/ for scoring config
  3. For each candidate result, checks declared scorer IDs
  4. If a scorer script exists at scripts/scorers/<id>.py, runs it
  5. Merges results back into run.json
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCORER_DIR = ROOT / "scripts" / "scorers"
SUITES_DIR = ROOT / "suites"


def resolve_scenario(scenario_id: str) -> dict | None:
    """Load a scenario JSON from the suites directory by ID.

    The convention is <suite>.<name> → suites/<suite>/<name>.json.
    """
    dot = scenario_id.find(".")
    if dot < 0:
        return None
    suite = scenario_id[:dot]
    name = scenario_id[dot + 1:]
    candidates = [
        SUITES_DIR / suite / f"{name}.json",
        SUITES_DIR / suite / f"{scenario_id}.json",
    ]
    for path in candidates:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return None


def discover_scorer_scripts() -> dict[str, pathlib.Path]:
    """Map scorer ID → script path by scanning scripts/scorers/<id>.py."""
    found: dict[str, pathlib.Path] = {}
    if not SCORER_DIR.exists():
        return found
    for entry in SCORER_DIR.iterdir():
        if entry.suffix == ".py" and entry.stem != "__init__":
            found[entry.stem] = entry
    return found


def run_scorer_script(
    script_path: pathlib.Path,
    fixture_dir: str | None,
    artifact_dir: str | None,
    scenario_params: dict | None,
    threshold: float | None,
    timeout: int = 120,
) -> dict:
    """Run a scorer script and return its ScoreResult-compatible dict."""
    cmd: list[str | pathlib.Path] = [sys.executable, script_path]

    if fixture_dir:
        cmd.extend(["--fixture-dir", str(fixture_dir)])
    if artifact_dir:
        cmd.extend(["--artifact-dir", str(artifact_dir)])
    if threshold is not None:
        cmd.extend(["--threshold", str(threshold)])
    if scenario_params:
        cmd.extend(["--params", json.dumps(scenario_params)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return {
                "scorer_id": script_path.stem,
                "scorer_name": script_path.stem.replace("-", " ").title(),
                "scoring_kind": "script",
                "success": False,
                "error": f"Script exited {result.returncode}: {stderr[:500] if stderr else '(no stderr)'}",
                "human_summary": f"FAIL: {script_path.stem}: script failed",
            }

        # Parse JSON from the last JSON-object line in stdout
        result_data = None
        for line in reversed(stdout.split("\n")):
            line = line.strip()
            if line and line[0] == "{":
                try:
                    result_data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        if result_data is None:
            return {
                "scorer_id": script_path.stem,
                "scorer_name": script_path.stem.replace("-", " ").title(),
                "scoring_kind": "script",
                "success": False,
                "error": f"No JSON output from scorer script. stdout: {stdout[:500]}",
                "human_summary": f"FAIL: {script_path.stem}: no JSON output",
            }

        # Fill in defaults
        result_data.setdefault("scorer_id", script_path.stem)
        result_data.setdefault("scorer_name",
            script_path.stem.replace("-", " ").title())
        result_data.setdefault("scoring_kind", "script")
        result_data.setdefault("success", True)
        result_data.setdefault("detail", {})

        return result_data

    except subprocess.TimeoutExpired:
        return {
            "scorer_id": script_path.stem,
            "scorer_name": script_path.stem.replace("-", " ").title(),
            "scoring_kind": "script",
            "success": False,
            "error": f"Scorer script timed out after {timeout}s",
            "human_summary": f"FAIL: {script_path.stem}: timed out",
        }
    except Exception as ex:
        return {
            "scorer_id": script_path.stem,
            "scorer_name": script_path.stem.replace("-", " ").title(),
            "scoring_kind": "script",
            "success": False,
            "error": str(ex),
            "human_summary": f"FAIL: {script_path.stem}: {ex}",
        }


def score_run(run_dir: str, verbose: bool = False) -> int:
    """Run the scoring pipeline for a single run directory."""
    run_json_path = pathlib.Path(run_dir) / "run.json"
    if not run_json_path.exists():
        print(f"ERROR: no run.json found in {run_dir}", file=sys.stderr)
        return 1

    with open(run_json_path) as f:
        run_data = json.load(f)

    scorer_scripts = discover_scorer_scripts()
    if not scorer_scripts:
        print("WARNING: no scorer scripts found in scripts/scorers/", file=sys.stderr)

    if verbose:
        print(f"Scoring run: {run_data.get('run_id', '?')}")
        print(f"Available scorer scripts: {list(scorer_scripts.keys())}")
        print()

    changes_made = 0

    for scenario_result in run_data.get("results", []):
        scenario_id = scenario_result.get("scenario_id", "?")
        scenario = resolve_scenario(scenario_id)

        if scenario is None:
            if verbose:
                print(f"  {scenario_id}: no scenario JSON found, skipping")
            continue

        scoring_cfg = scenario.get("scoring", {})
        declared_scorers = scoring_cfg.get("scorers", [])
        params = scoring_cfg.get("parameters", {})
        thresholds = scoring_cfg.get("thresholds", {})

        if verbose:
            print(f"  {scenario_id}: declared scorers: {declared_scorers}")

        for candidate_result in scenario_result.get("candidate_results", []):
            candidate_id = candidate_result.get("candidate_id", "?")
            existing_score_ids = {
                s.get("scorer_id") for s in candidate_result.get("scores", [])
            }
            output = candidate_result.get("output") or {}
            fixture_dir = output.get("fixture_dir") if isinstance(output, dict) else None
            artifact_dir = candidate_result.get("artifact_directory")

            if verbose:
                print(f"    {candidate_id}: fixture={fixture_dir}")
                print(f"      existing scores: {existing_score_ids}")

            for scorer_id in declared_scorers:
                script = scorer_scripts.get(scorer_id)
                if script is None:
                    if verbose:
                        print(f"      ~ {scorer_id}: no Python scorer script, skipping")
                    continue

                # Check existing score — if there's one from a .NET scorer and we
                # have a Python script for the same ID, replace it. The Python
                # script is the canonical handler for language-agnostic testing.
                existing = [s for s in candidate_result.get("scores", [])
                            if s.get("scorer_id") == scorer_id]
                if existing and existing[0].get("scoring_kind") != "script":
                    if verbose:
                        print(f"      ~ {scorer_id}: replacing .NET score with Python scorer")
                    candidate_result["scores"] = [
                        s for s in candidate_result.get("scores", [])
                        if s.get("scorer_id") != scorer_id
                    ]
                elif existing:
                    if verbose:
                        print(f"      ~ {scorer_id}: already scored, skipping")
                    continue

                scorer_params = params.get(scorer_id)
                threshold = thresholds.get(scorer_id)

                if verbose:
                    print(f"      > {scorer_id}: running {script.name}...")

                score = run_scorer_script(
                    script, fixture_dir, artifact_dir,
                    scorer_params, threshold,
                )

                candidate_result.setdefault("scores", []).append(score)
                changes_made += 1

                if verbose:
                    summary = score.get("human_summary", "?")
                    print(f"      < {scorer_id}: {summary}")

    # Write updated run.json
    with open(run_json_path, "w") as f:
        json.dump(run_data, f, indent=2)

    print(f"\nDone. {changes_made} score(s) added/written to {run_json_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="GoblinBench scoring pipeline — runs per-language scorer scripts")
    parser.add_argument("run_dir", help="Path to a run directory containing run.json")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Detailed progress output")
    args = parser.parse_args()

    return score_run(args.run_dir, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
