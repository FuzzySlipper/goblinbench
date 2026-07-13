#!/usr/bin/env python3
"""GoblinBench runner entrypoint — canonical Python runner.

Discovers scenarios under ``suites/``, runs the matching candidate runner for
each (scenario × candidate) cell, applies declared scorers, and writes the
artifact tree to ``runs/<run-id>/`` using the same on-disk contract as the
.NET runner — so ``gb-score.py`` and ``gb-results.py`` consume it unchanged.

Usage mirrors the .NET CLI:

    python3 scripts/gb-run.py
    python3 scripts/gb-run.py --suite coding --candidate demo-noop
    python3 scripts/gb-run.py --scenario coding.maintainability-mini-service-python
    python3 scripts/gb-run.py --candidates path/to/candidates.json

After the run completes (mirroring Program.cs) it hands off to the existing
``scripts/gb-score.py`` post-processor, which merges Python-only scorer
plugins (structure-metrics, maintainability-metrics, coding-tests re-score)
back into run.json.

Milestone 1: NoOp + Scripted runners, Latency + SchemaCompliance scorers.
OpenAiChat / CodingAgent runners land in Milestone 2.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

# Make the sibling ``gb`` package importable regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gb import discovery  # noqa: E402
from gb.context import RunContext  # noqa: E402
from gb.environment import finalize_environment, refresh_environment_outcomes  # noqa: E402
from gb.models import (  # noqa: E402
    CandidateConfig,
    CandidateKind,
    CandidateResult,
    PerScenarioResult,
    RunResult,
    ScoreResult,
    TraceEvent,
)
from gb.registry import (  # noqa: E402
    active_scorers,
    default_runners,
    default_scorers,
    pick_runner,
)
from gb.serialize import dumps, now_iso  # noqa: E402
from gb.store import DbPaths, ingest_run, open_db, prune_run_files  # noqa: E402

# Default ring-buffer size for on-disk run files. Override via the
# GOBLINBENCH_RUN_FILE_RETENTION env var. DB history is unaffected (canonical).
DEFAULT_RUN_FILE_RETENTION = 20


def resolve_repo_root() -> str:
    """Walk up from this file to find the repo root (has both ``suites/`` and ``src/``)."""
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(d, "suites")) and os.path.isdir(os.path.join(d, "src")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def load_candidates(path: str) -> list[CandidateConfig]:
    if not os.path.exists(path):
        print(f"Warning: {path} not found — using built-in no-op demo candidate.")
        print("  Create candidates.json at the repo root, or pass --candidates <path>.")
        return [
            CandidateConfig(
                id="noop-demo",
                name="No-Op Demo Candidate",
                kind=CandidateKind.Unknown,
                cli_command="noop",
            )
        ]
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [CandidateConfig.from_dict(c) for c in raw]


def expand_filters(filters: list[str]) -> list[str]:
    out: list[str] = []
    for f in filters:
        for piece in f.split(","):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def filter_candidates_by_id(
    candidates: list[CandidateConfig], filters: list[str]
) -> list[CandidateConfig]:
    wanted = {w.lower() for w in expand_filters(filters)}
    if not wanted:
        return list(candidates)
    return [c for c in candidates if c.id.lower() in wanted]


def _scenario_context(base: RunContext, scenario_id: str) -> RunContext:
    return RunContext(
        run_id=base.run_id,
        started_at=base.started_at,
        run_directory=base.run_directory,
        runs_root=base.runs_root,
        repo_root=base.repo_root,
        scenario_id=scenario_id,
        label=base.label,
        metadata=base.metadata,
    )


def _run_candidate(
    scenario, candidate, context, runner, runners, scorers, timeout
):  # type: ignore[no-untyped-def]
    """Execute one candidate + its scorers, writing scores.json + trace.jsonl.

    Mirrors the per-candidate block of Program.cs: try the runner; on success
    run only the declared scorers; write scores.json and the trace.jsonl that
    runners accumulated; swallow scorer exceptions into failure ScoreResults.
    """
    result = runner.run(scenario, candidate, context, timeout=timeout)

    # Resolve declared scorers (or all, if none declared).
    for scorer in active_scorers(scorers, scenario):
        try:
            result.scores.append(scorer.score(scenario, candidate, result, context))
        except Exception as ex:  # noqa: BLE001 — scorer isolation mirrors C#
            result.scores.append(
                ScoreResult(
                    scorer_id=getattr(scorer, "id", ""),
                    scorer_name=getattr(scorer, "name", ""),
                    success=False,
                    error=str(ex),
                )
            )

    result.environment = finalize_environment(
        candidate, scenario, getattr(runner, "name", type(runner).__name__), result
    )
    environment_path = os.path.join(
        context.candidate_artifacts_directory(candidate.id), "environment.json"
    )
    os.makedirs(os.path.dirname(environment_path), exist_ok=True)
    with open(environment_path, "w", encoding="utf-8") as f:
        f.write(dumps(result.environment))

    # Write scores.json artifact.
    scores_path = context.candidate_scores_path(candidate.id)
    scores_dir = os.path.dirname(scores_path)
    if scores_dir:
        os.makedirs(scores_dir, exist_ok=True)
    with open(scores_path, "w", encoding="utf-8") as f:
        f.write(dumps(result.scores))

    # Write trace.jsonl (one compact object per line) — mirrors Program.cs
    # flushing trace centrally so every runner gets it for free.
    if result.trace:
        trace_path = context.candidate_trace_path(candidate.id)
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        lines = [dumps(t, indent=None) for t in result.trace]
        with open(trace_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gb-run", description="GoblinBench runner (Python port)")
    parser.add_argument("--suite")
    parser.add_argument("--scenario")
    parser.add_argument("--candidates", help="path to candidates.json (default: repo candidates.json)")
    parser.add_argument("--candidate", action="append", default=[], help="candidate id (repeatable / comma-sep)")
    parser.add_argument("--skip-scenario", "--exclude-scenario", dest="skip_scenario", action="append", default=[],
                        help="scenario id to skip (repeatable / comma-sep)")
    args = parser.parse_args(argv)

    print("=== GoblinBench Runner (Python) ===")
    print()

    repo_root = resolve_repo_root()
    suites_root = os.path.join(repo_root, "suites")
    runs_root = os.path.join(repo_root, "runs")
    candidates_file = os.path.join(repo_root, "candidates.json")
    if args.candidates:
        candidates_file = args.candidates if os.path.isabs(args.candidates) else os.path.join(repo_root, args.candidates)

    # Collision-safe run id: timestamp + 8 hex chars from a uuid (matches C# Guid[..8]).
    run_id = f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run_dir = os.path.join(runs_root, run_id)

    print(f"Run ID:   {run_id}")
    print(f"Suites:   {suites_root}")
    print(f"Runs:     {runs_root}")
    if args.suite:
        print(f"Filter:   --suite {args.suite}")
    if args.scenario:
        print(f"Filter:   --scenario {args.scenario}")
    if args.candidate:
        print(f"Filter:   --candidate {','.join(expand_filters(args.candidate))}")
    if args.skip_scenario:
        print(f"Skip:     --skip-scenario {','.join(expand_filters(args.skip_scenario))}")
    print()

    # Discover scenarios.
    print("Discovering scenarios... ", end="", flush=True)
    all_scenarios = discovery.discover(suites_root)
    scenarios = discovery.filter_scenarios(
        all_scenarios,
        suite=args.suite,
        scenario_id=args.scenario,
        skip=expand_filters(args.skip_scenario),
    )
    print(f"{len(scenarios)} found (of {len(all_scenarios)} total)")

    if not scenarios:
        print("Error: no scenarios found. Create .json files under suites/.", file=sys.stderr)
        return 1

    for s in scenarios:
        print(f"  - {s.id} (v{s.version}) [{s.suite}]")
    print()

    # Load + filter candidates.
    candidates = filter_candidates_by_id(load_candidates(candidates_file), args.candidate)
    if not candidates:
        print("Error: no candidates matched --candidate filter.", file=sys.stderr)
        return 1
    print(f"Candidates: {len(candidates)} (from {os.path.basename(candidates_file)})")
    for c in candidates:
        print(f"  - {c.id} ({c.kind.value})")
    print()

    # Run context.
    base_context = RunContext(
        run_id=run_id,
        started_at=now_iso(),
        run_directory=run_dir,
        runs_root=runs_root,
        repo_root=repo_root,
        label=f"CLI run {time.strftime('%Y-%m-%d %H:%M:%S')}",
    )
    os.makedirs(run_dir, exist_ok=True)

    runners = default_runners()
    scorers = default_scorers()

    run_result = RunResult(
        run_id=run_id,
        started_at=base_context.started_at,
        label=base_context.label,
    )

    for scenario in scenarios:
        print(f"--- Scenario: {scenario.id} ---")
        scenario_result = PerScenarioResult(scenario_id=scenario.id, scenario_version=scenario.version)
        run_result.scenarios.append(scenario.id)

        scenario_context = _scenario_context(base_context, scenario.id)
        timeout = scenario.timeout_seconds if scenario.timeout_seconds > 0 else 300

        for candidate in candidates:
            print(f"  Candidate: {candidate.id} ... ", end="", flush=True)

            runner = pick_runner(runners, candidate)
            if runner is None:
                print("SKIP (no runner)")
                scenario_result.candidate_results.append(CandidateResult(
                    candidate_id=candidate.id,
                    candidate_name=candidate.name,
                    candidate_kind=candidate.kind,
                    success=False,
                    error="No compatible candidate runner found.",
                ))
                continue

            try:
                cr = _run_candidate(
                    scenario, candidate, scenario_context, runner, runners, scorers, timeout
                )
                scenario_result.candidate_results.append(cr)
                print("OK" if cr.success else "FAIL")
            except Exception as ex:  # noqa: BLE001 — runner isolation mirrors C#
                print(f"ERROR: {ex}")
                traceback.print_exc()
                scenario_result.candidate_results.append(CandidateResult(
                    candidate_id=candidate.id,
                    candidate_name=candidate.name,
                    candidate_kind=candidate.kind,
                    success=False,
                    error=str(ex),
                ))

        run_result.results.append(scenario_result)

    run_result.completed_at = now_iso()

    # Write run.json.
    run_json_path = os.path.join(run_dir, "run.json")
    with open(run_json_path, "w", encoding="utf-8") as f:
        f.write(dumps(run_result))

    # Hand off to the existing Python scoring pipeline (gb-score.py), mirroring
    # Program.cs. It re-reads run.json and merges Python scorer plugins back in.
    python_pipeline = os.path.join(repo_root, "scripts", "gb-score.py")
    if os.path.exists(python_pipeline):
        print("Running Python scoring pipeline... ", end="", flush=True)
        try:
            proc = subprocess.run(
                ["python3", python_pipeline, run_dir],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                print("OK")
            else:
                print(f"WARN (exit {proc.returncode})")
                for ln in (proc.stderr or "").splitlines():
                    if ln.strip():
                        print(f"  pipeline: {ln}")
            # Re-read run.json in case the pipeline updated scores.
            with open(run_json_path, "r", encoding="utf-8") as f:
                run_result_dump = json.load(f)
        except Exception as ex:  # noqa: BLE001
            print(f"ERROR: {ex}")
        else:
            del run_result_dump  # not used further; run.json on disk is authoritative

    # Post-processors can add or replace scorer results. Refresh the stable
    # environment outcome only after that pipeline so run.json, the artifact,
    # and the canonical store all retain the same scored truth.
    with open(run_json_path, "r", encoding="utf-8") as f:
        scored_run = json.load(f)
    environment_artifacts = refresh_environment_outcomes(scored_run)
    with open(run_json_path, "w", encoding="utf-8") as f:
        f.write(dumps(scored_run))
    for artifact_directory, environment in environment_artifacts:
        artifact_path = os.path.join(artifact_directory, "environment.json")
        os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
        with open(artifact_path, "w", encoding="utf-8") as f:
            f.write(dumps(environment))

    # Ingest the finished run into the canonical SQLite store (inline artifacts
    # + scores + representative samples). The DB is the durable record; the
    # on-disk runs/ files are now scratch space bounded by a ring buffer.
    try:
        paths = DbPaths.resolve(repo_root)
        conn = open_db(paths.db_path)
        try:
            ingest_run(conn, Path(run_json_path), repo_root)
            conn.commit()
        finally:
            conn.close()
        retention = int(os.environ.get("GOBLINBENCH_RUN_FILE_RETENTION", DEFAULT_RUN_FILE_RETENTION))
        pruned = prune_run_files(paths.runs_root, retention)
        if pruned:
            print(f"Ring buffer: pruned {len(pruned)} old run dir(s) from disk (kept {retention} most recent; DB retains full history).")
    except Exception as ex:  # noqa: BLE001 — store failure must not mask a successful run
        print(f"WARN: store ingest/prune failed: {ex}")

    print()
    print(f"Run complete. Artifacts: {run_dir}")
    print(f"  run.json: {os.path.basename(run_json_path)}")

    for scenario_result in run_result.results:
        for cr in scenario_result.candidate_results:
            cand_dir = _scenario_context(base_context, scenario_result.scenario_id).candidate_directory(
                cr.candidate_id
            )
            status = "OK" if cr.success else "FAIL"
            print(f"  {scenario_result.scenario_id}/{cr.candidate_id}: {status} ({cr.duration_ms}ms) {cand_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
