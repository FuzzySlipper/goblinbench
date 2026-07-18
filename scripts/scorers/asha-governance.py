#!/usr/bin/env python3
"""Score the mixed-language Mini ASHA authority and governance fixture.

The candidate workspace is copied to a temporary directory, protected guidance
and gate inputs are compared with the canonical fixture, hidden regressions are
overlaid, and each architecture/correctness gate is executed independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Iterable


REPO = pathlib.Path(__file__).resolve().parents[2]
CANONICAL = REPO / "fixtures/coding/asha-authority-door"
HIDDEN = REPO / "tests/fixtures/asha-authority-door-hidden"
SKIP_NAMES = {".git", "node_modules", "target", "dist", "coverage", "__pycache__"}
PROTECTED_GLOBS = (
    "AGENTS.md",
    "README.md",
    "Cargo.toml",
    "Cargo.lock",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "docs/**/*",
    "governance/**/*",
    "harness/**/*",
    "crates/*/Cargo.toml",
    "crates/*/tests/**/*",
    "ts/packages/*/package.json",
    "ts/tests/**/*",
)


@dataclass(frozen=True)
class Gate:
    gate_id: str
    name: str
    weight: float
    critical: bool
    commands: tuple[tuple[str, ...], ...]
    timeout_seconds: int


GATES = (
    Gate(
        "authority-behavior",
        "Rust authority behavior and atomicity",
        0.25,
        True,
        (("cargo", "test", "-p", "rule-door", "--no-fail-fast"),),
        120,
    ),
    Gate(
        "replay-determinism",
        "Replay correctness and deterministic hashing",
        0.20,
        True,
        (("cargo", "test", "-p", "sim-replay", "--no-fail-fast"),),
        120,
    ),
    Gate(
        "generated-contracts",
        "Rust-generated TypeScript contract parity",
        0.15,
        True,
        (("cargo", "run", "-q", "-p", "protocol-codegen", "--", "--check"),),
        120,
    ),
    Gate(
        "dependency-boundaries",
        "Ownership cells and dependency boundaries",
        0.15,
        True,
        (("python3", "harness/check_boundaries.py"),),
        60,
    ),
    Gate(
        "typescript-expression-projection",
        "TypeScript policy, projection consumption, and strict types",
        0.15,
        True,
        (
            ("npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"),
            ("npm", "test"),
        ),
        180,
    ),
    Gate(
        "render-projection",
        "Rust-owned renderer projection",
        0.05,
        False,
        (("cargo", "test", "-p", "render-projection", "--no-fail-fast"),),
        120,
    ),
    Gate(
        "rust-quality",
        "Rust formatting and warning-free ownership cells",
        0.03,
        False,
        (
            ("cargo", "fmt", "--check", "--all"),
            ("cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"),
        ),
        180,
    ),
    Gate(
        "guidance-vocabulary",
        "Asha vocabulary and source-shape guidance",
        0.02,
        False,
        (("python3", "harness/check_guidance.py"),),
        60,
    ),
)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_files(root: pathlib.Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for pattern in PROTECTED_GLOBS:
        for path in root.glob(pattern):
            if path.is_file() and not any(part in SKIP_NAMES for part in path.parts):
                files[path.relative_to(root).as_posix()] = sha256(path)
    return files


def integrity_violations(candidate: pathlib.Path) -> list[str]:
    expected = protected_files(CANONICAL)
    actual = protected_files(candidate)
    violations: list[str] = []
    for relative, expected_hash in sorted(expected.items()):
        actual_hash = actual.get(relative)
        if actual_hash is None:
            violations.append(f"protected file removed: {relative}")
        elif actual_hash != expected_hash:
            violations.append(f"protected file changed: {relative}")
    return violations


def ignore_copy(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_NAMES}


def install_hidden_tests(workspace: pathlib.Path) -> None:
    destinations = {
        "rule_hidden.rs": workspace / "crates/rule-door/tests/goblinbench_hidden.rs",
        "replay_hidden.rs": workspace / "crates/sim-replay/tests/goblinbench_hidden.rs",
        "ts_hidden.test.ts": workspace / "ts/tests/goblinbench-hidden.test.ts",
    }
    for source_name, destination in destinations.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HIDDEN / source_name, destination)


def command_display(command: Iterable[str]) -> str:
    return " ".join(command)


def run_gate(gate: Gate, workspace: pathlib.Path, environment: dict[str, str]) -> dict:
    started = time.perf_counter()
    command_results: list[dict] = []
    passed = True
    for command in gate.commands:
        command_started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                timeout=gate.timeout_seconds,
            )
            output = (result.stdout + result.stderr)[-6000:]
            command_passed = result.returncode == 0
            command_results.append(
                {
                    "command": command_display(command),
                    "exit_code": result.returncode,
                    "passed": command_passed,
                    "duration_ms": int((time.perf_counter() - command_started) * 1000),
                    "output": output,
                }
            )
        except subprocess.TimeoutExpired as error:
            captured = ""
            if isinstance(error.stdout, bytes):
                captured += error.stdout.decode(errors="replace")
            elif error.stdout:
                captured += error.stdout
            if isinstance(error.stderr, bytes):
                captured += error.stderr.decode(errors="replace")
            elif error.stderr:
                captured += error.stderr
            command_passed = False
            command_results.append(
                {
                    "command": command_display(command),
                    "exit_code": None,
                    "passed": False,
                    "timed_out": True,
                    "duration_ms": int((time.perf_counter() - command_started) * 1000),
                    "output": captured[-6000:],
                }
            )
        except FileNotFoundError as error:
            command_passed = False
            command_results.append(
                {
                    "command": command_display(command),
                    "exit_code": None,
                    "passed": False,
                    "duration_ms": int((time.perf_counter() - command_started) * 1000),
                    "output": str(error),
                }
            )
        if not command_passed:
            passed = False
            break

    return {
        "id": gate.gate_id,
        "name": gate.name,
        "weight": gate.weight,
        "critical": gate.critical,
        "passed": passed,
        "earned": gate.weight if passed else 0.0,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "commands": command_results,
    }


def score_fixture(fixture_dir: pathlib.Path, threshold: float) -> dict:
    violations = integrity_violations(fixture_dir)
    if violations:
        gate_results = [
            {
                "id": gate.gate_id,
                "name": gate.name,
                "weight": gate.weight,
                "critical": gate.critical,
                "passed": False,
                "earned": 0.0,
                "duration_ms": 0,
                "skipped": "protected input integrity failed",
                "commands": [],
            }
            for gate in GATES
        ]
    else:
        with tempfile.TemporaryDirectory(prefix="goblinbench-asha-") as temporary:
            workspace = pathlib.Path(temporary) / "fixture"
            shutil.copytree(fixture_dir, workspace, ignore=ignore_copy)
            install_hidden_tests(workspace)
            environment = os.environ.copy()
            environment.update(
                {
                    "CARGO_TERM_COLOR": "never",
                    "NO_COLOR": "1",
                    "npm_config_audit": "false",
                    "npm_config_fund": "false",
                }
            )
            gate_results = [run_gate(gate, workspace, environment) for gate in GATES]

    raw_score = sum(result["earned"] for result in gate_results)
    critical_failures = [
        result["id"] for result in gate_results if result["critical"] and not result["passed"]
    ]
    if violations:
        score = 0.0
    elif critical_failures:
        score = min(raw_score, 0.69)
    else:
        score = raw_score
    score = round(score, 4)
    passed = not violations and not critical_failures and score >= threshold
    passed_count = sum(1 for result in gate_results if result["passed"])

    return {
        "scorer_id": "asha-governance",
        "scorer_name": "Mini ASHA Governance and Authority",
        "scoring_kind": "deterministic",
        "success": True,
        "score": score,
        "passed": passed,
        "threshold": threshold,
        "human_summary": (
            f"PASS: {passed_count}/{len(gate_results)} gates, score {score:.2f}"
            if passed
            else f"FAIL: {passed_count}/{len(gate_results)} gates, score {score:.2f}"
        ),
        "explanation": (
            "Protected guidance and tests intact; " if not violations else "Protected inputs changed; "
        )
        + (
            "all critical gates passed."
            if not critical_failures
            else f"critical failures: {', '.join(critical_failures)}."
        ),
        "detail": {
            "fixture": "asha-authority-door",
            "protected_input_violations": violations,
            "critical_failures": critical_failures,
            "raw_weighted_score": round(raw_score, 4),
            "critical_failure_cap": 0.69,
            "gates": gate_results,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--params")
    args = parser.parse_args()

    fixture_dir = pathlib.Path(args.fixture_dir).resolve()
    if not fixture_dir.is_dir():
        print(
            json.dumps(
                {
                    "scorer_id": "asha-governance",
                    "scorer_name": "Mini ASHA Governance and Authority",
                    "scoring_kind": "deterministic",
                    "success": False,
                    "score": 0.0,
                    "passed": False,
                    "human_summary": "FAIL: fixture directory not found",
                    "error": f"fixture directory not found: {fixture_dir}",
                }
            )
        )
        return

    result = score_fixture(fixture_dir, args.threshold)
    if args.artifact_dir:
        artifact_dir = pathlib.Path(args.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "asha-governance.json").write_text(
            json.dumps(result["detail"], indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
