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

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from gb.codebase_analysis import extract_findings
from gb.context import RunContext
from gb.environment import refresh_environment_outcomes
from gb.models import CandidateConfig, CandidateKind, CandidateResult, Scenario
from gb.scorers.codebase_analysis_gold import CodebaseAnalysisGoldScorer
from gb.scorers.fuzzy_agent_behavior import FuzzyAgentBehaviorScorer


ROOT = SCRIPT_DIR.parent
SCORER_DIR = ROOT / "scripts" / "scorers"
SUITES_DIR = ROOT / "suites"


def resolve_scenario(scenario_id: str) -> dict | None:
    """Load a scenario JSON from the suites directory by ID.

    The convention is <suite>.<name> → suites/<suite>/<name>.json.
    """
    dot = scenario_id.find(".")
    candidates: list[pathlib.Path] = []
    if dot >= 0:
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

    # Older coding scenarios have IDs without a ``suite.name`` prefix. Search
    # by declared ID so script scorers still attach to environment-realized rows.
    for path in SUITES_DIR.rglob("*.json"):
        try:
            with open(path) as f:
                scenario = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if scenario.get("id") == scenario_id:
            return scenario
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


def _retained_fixture_dir(
    run_dir: pathlib.Path,
    candidate_result: dict,
) -> tuple[str | None, bool]:
    output = candidate_result.get("output") or {}
    fixture_dir = output.get("fixture_dir") if isinstance(output, dict) else None
    if isinstance(fixture_dir, str) and pathlib.Path(fixture_dir).is_dir():
        return fixture_dir, False

    artifact_dir = candidate_result.get("artifact_directory")
    if not isinstance(artifact_dir, str) or not artifact_dir:
        return None, False
    artifact_path = pathlib.Path(artifact_dir)
    if not artifact_path.is_absolute():
        root_relative = ROOT / artifact_path
        run_relative = run_dir / artifact_path
        artifact_path = root_relative if root_relative.exists() else run_relative
    candidate_dir = artifact_path.parent if artifact_path.name == "artifacts" else artifact_path
    retained = (candidate_dir / "fixture").resolve()
    try:
        retained.relative_to(run_dir.resolve())
    except ValueError:
        return None, False
    if not retained.is_dir():
        return None, False

    normalized_output = output if isinstance(output, dict) else {}
    normalized_output["fixture_dir"] = str(retained)
    normalized_output["fixture_recovery"] = {
        "source": "retained_candidate_fixture",
        "reason": "runner result omitted fixture_dir after failure",
    }
    candidate_result["output"] = normalized_output
    return str(retained), True


def _write_candidate_scores(candidate_result: dict) -> None:
    artifact_dir = candidate_result.get("artifact_directory")
    if not isinstance(artifact_dir, str) or not artifact_dir:
        return
    artifact_path = pathlib.Path(artifact_dir)
    if not artifact_path.is_absolute():
        artifact_path = ROOT / artifact_path
    candidate_dir = artifact_path.parent if artifact_path.name == "artifacts" else artifact_path
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "scores.json").write_text(
        json.dumps(candidate_result.get("scores", []), indent=2), encoding="utf-8"
    )


def _refresh_in_process_score(
    scorer_id: str,
    scenario_raw: dict,
    candidate_raw: dict,
    run_data: dict,
    run_dir: pathlib.Path,
) -> dict | None:
    scorers = {
        "fuzzy-agent-behavior": FuzzyAgentBehaviorScorer(),
        "codebase-analysis-gold": CodebaseAnalysisGoldScorer(),
    }
    scorer = scorers.get(scorer_id)
    if scorer is None:
        return None
    scenario = Scenario.from_dict(scenario_raw)
    kind_raw = candidate_raw.get("candidate_kind") or "Unknown"
    try:
        candidate_kind = CandidateKind(kind_raw)
    except ValueError:
        candidate_kind = CandidateKind.Unknown
    output = candidate_raw.get("output")
    if not isinstance(output, dict):
        output = {}
        candidate_raw["output"] = output
    raw_response = candidate_raw.get("raw_response")
    if scorer_id == "codebase-analysis-gold" and isinstance(raw_response, str):
        findings = extract_findings(raw_response)
        if findings is not None:
            output["findings"] = findings
            if output.get("finding_extraction_status") != "success":
                output["finding_extraction_status"] = "recovered_json"
            artifact_dir = candidate_raw.get("artifact_directory")
            if isinstance(artifact_dir, str) and artifact_dir:
                artifact_path = pathlib.Path(artifact_dir)
                if not artifact_path.is_absolute():
                    artifact_path = ROOT / artifact_path
                artifact_path.mkdir(parents=True, exist_ok=True)
                (artifact_path / "findings.json").write_text(
                    json.dumps({"findings": findings}, indent=2), encoding="utf-8"
                )
    candidate = CandidateConfig(
        id=str(candidate_raw.get("candidate_id") or "unknown"),
        name=str(candidate_raw.get("candidate_name") or ""),
        kind=candidate_kind,
    )
    result = CandidateResult(
        candidate_id=candidate.id,
        candidate_name=candidate.name,
        candidate_kind=candidate_kind,
        success=bool(candidate_raw.get("success")),
        error=candidate_raw.get("error"),
        duration_ms=int(candidate_raw.get("duration_ms") or 0),
        raw_response=raw_response,
        parsed_response=candidate_raw.get("parsed_response"),
        output=output,
        artifact_directory=candidate_raw.get("artifact_directory"),
        environment=candidate_raw.get("environment") or {},
    )
    context = RunContext(
        run_id=str(run_data.get("run_id") or run_dir.name),
        run_directory=str(run_dir),
        runs_root=str(run_dir.parent),
        repo_root=str(ROOT),
        scenario_id=scenario.id,
    )
    score = scorer.score(scenario, candidate, result, context).json_dict()
    detail = score.get("detail")
    if not isinstance(detail, dict):
        detail = {}
        score["detail"] = detail
    detail["rescored_from_retained_artifacts"] = True
    return score


def score_run(
    run_dir: str,
    verbose: bool = False,
    retry_failed: bool = False,
    refresh_in_process: bool = False,
) -> int:
    """Run the scoring pipeline for a single run directory."""
    run_dir_path = pathlib.Path(run_dir).resolve()
    run_json_path = run_dir_path / "run.json"
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
    recovered_fixture_count = 0

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
            fixture_dir, recovered_fixture = _retained_fixture_dir(
                run_dir_path, candidate_result
            )
            if recovered_fixture:
                recovered_fixture_count += 1
            artifact_dir = candidate_result.get("artifact_directory")
            candidate_changed = recovered_fixture

            if verbose:
                print(f"    {candidate_id}: fixture={fixture_dir}")
                print(f"      existing scores: {existing_score_ids}")

            for scorer_id in declared_scorers:
                if refresh_in_process:
                    refreshed = _refresh_in_process_score(
                        scorer_id, scenario, candidate_result, run_data, run_dir_path
                    )
                    if refreshed is not None:
                        candidate_result["scores"] = [
                            score for score in candidate_result.get("scores", [])
                            if score.get("scorer_id") != scorer_id
                        ]
                        candidate_result.setdefault("scores", []).append(refreshed)
                        changes_made += 1
                        candidate_changed = True
                        if verbose:
                            print(
                                f"      < {scorer_id}: "
                                f"{refreshed.get('human_summary', '?')} (refreshed)"
                            )
                        continue
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
                elif existing and retry_failed and not all(
                    bool(score.get("success")) for score in existing
                ):
                    if verbose:
                        print(f"      ~ {scorer_id}: retrying failed script score")
                    candidate_result["scores"] = [
                        score for score in candidate_result.get("scores", [])
                        if score.get("scorer_id") != scorer_id
                    ]
                elif existing:
                    if verbose:
                        print(f"      ~ {scorer_id}: already scored, skipping")
                    continue

                scorer_params = params.get(scorer_id)
                threshold = thresholds.get(scorer_id)
                scorer_timeout = 120
                if isinstance(scorer_params, dict):
                    configured_timeout = scorer_params.get("timeout_seconds")
                    if isinstance(configured_timeout, (int, float)) and configured_timeout > 0:
                        scorer_timeout = int(configured_timeout)

                if verbose:
                    print(f"      > {scorer_id}: running {script.name}...")

                score = run_scorer_script(
                    script, fixture_dir, artifact_dir,
                    scorer_params, threshold,
                    timeout=scorer_timeout,
                )
                if recovered_fixture:
                    detail = score.get("detail")
                    if not isinstance(detail, dict):
                        detail = {}
                        score["detail"] = detail
                    detail["fixture_recovered_after_runner_failure"] = True

                candidate_result.setdefault("scores", []).append(score)
                changes_made += 1
                candidate_changed = True

                if verbose:
                    summary = score.get("human_summary", "?")
                    print(f"      < {scorer_id}: {summary}")
            if candidate_changed:
                _write_candidate_scores(candidate_result)

    if changes_made or recovered_fixture_count:
        run_data.setdefault("metadata", {}).setdefault("post_score_events", []).append({
            "kind": "gb-score",
            "recorded_at_unix": int(time.time()),
            "retry_failed": retry_failed,
            "refresh_in_process": refresh_in_process,
            "scores_written": changes_made,
            "retained_fixtures_recovered": recovered_fixture_count,
        })

    # Refresh environment outcome envelopes after replacing any score, matching
    # the normal gb-run post-processing order.
    for artifact_directory, environment in refresh_environment_outcomes(run_data):
        artifact_path = pathlib.Path(artifact_directory)
        if not artifact_path.is_absolute():
            artifact_path = ROOT / artifact_path
        artifact_path.mkdir(parents=True, exist_ok=True)
        (artifact_path / "environment.json").write_text(
            json.dumps(environment, indent=2), encoding="utf-8"
        )

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
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="replace and rerun existing script scores whose prior invocation failed",
    )
    parser.add_argument(
        "--refresh-in-process", action="store_true",
        help="re-run maintained in-process fuzzy and codebase-analysis scorers",
    )
    args = parser.parse_args()

    return score_run(
        args.run_dir,
        verbose=args.verbose,
        retry_failed=args.retry_failed,
        refresh_in_process=args.refresh_in_process,
    )


if __name__ == "__main__":
    sys.exit(main())
