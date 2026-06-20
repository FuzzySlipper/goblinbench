"""Deterministic coding runner — port of CodingCandidateRunner.cs.

Handles ``cli_command = "coding-scripted"``: copies a named fixture from
``fixtures/coding/{fixture_case}/`` into the run artifact dir and applies
``correct_patch.json`` if present, producing a known-correct file state for the
test scorer to validate against.

Returns ``output["fixture_dir"]`` so ``gb-score.py`` can locate the modified
fixture and run ``scripts/scorers/coding-tests.py`` against it.
"""

from __future__ import annotations

import json
import os
import time

from ..context import RunContext
from ..fsutil import SKIP_DIRS_SCRIPTED, copy_directory
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import now_iso


class CodingScriptedRunner:
    name = "coding"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return (candidate.cli_command or "").lower() == "coding-scripted"

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_at = now_iso()
        started_perf = time.perf_counter()

        def fail(error: str) -> CandidateResult:
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                success=False,
                error=error,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
            )

        fixture_case = _get_string_from_input(scenario, "fixture_case")
        if not fixture_case:
            return fail("Scenario input missing 'fixture_case'.")

        repo_root = context.repo_root or _find_repo_root(context.runs_root)
        fixture_source = os.path.join(repo_root, "fixtures", "coding", fixture_case)
        if not os.path.isdir(fixture_source):
            return fail(f"Fixture directory not found: {fixture_source}")

        # Copy fixture into run artifact directory.
        fixture_destination = os.path.join(context.candidate_directory(candidate.id), "fixture")
        copy_directory(fixture_source, fixture_destination, SKIP_DIRS_SCRIPTED)

        trace = [
            TraceEvent(
                timestamp=started_at,
                event="coding.fixture.copied",
                data={"source": fixture_source, "destination": fixture_destination},
            )
        ]

        # Apply correct_patch.json for the scripted path (dict[relpath, content]).
        patch_path = os.path.join(fixture_destination, "correct_patch.json")
        if os.path.isfile(patch_path):
            try:
                with open(patch_path, "r", encoding="utf-8") as f:
                    patch = json.load(f)
                if isinstance(patch, dict):
                    for rel_path, content in patch.items():
                        target = os.path.join(fixture_destination, rel_path)
                        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
                        with open(target, "w", encoding="utf-8") as out:
                            out.write(content if isinstance(content, str) else json.dumps(content))
                    trace.append(TraceEvent(
                        timestamp=now_iso(),
                        event="coding.patch.applied",
                        data={"files_patched": len(patch)},
                    ))
            except Exception as ex:  # noqa: BLE001
                return fail(f"Failed to apply correct_patch.json: {ex}")
        else:
            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.patch.skipped",
                data={"reason": "no correct_patch.json in fixture"},
            ))

        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        return CandidateResult(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            candidate_kind=candidate.kind,
            model_identity=ModelIdentity(
                model="scripted-patch",
                provider="goblinbench",
                display_name="Scripted Coding Runner (correct_patch.json)",
            ),
            success=True,
            duration_ms=duration_ms,
            raw_response=f"Applied correct_patch.json to fixture '{fixture_case}'",
            output={
                "fixture_dir": fixture_destination,
                "fixture_case": fixture_case,
            },
            trace=trace,
            artifact_directory=context.candidate_artifacts_directory(candidate.id),
        )


def _get_string_from_input(scenario: Scenario, key: str) -> str:
    v = scenario.input.get(key)
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _find_repo_root(runs_root: str) -> str:
    d = os.path.dirname(runs_root) or runs_root
    while True:
        if os.path.isdir(os.path.join(d, "suites")) and os.path.isdir(os.path.join(d, "src")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(runs_root) or runs_root
