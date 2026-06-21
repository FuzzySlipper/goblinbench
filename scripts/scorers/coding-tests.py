#!/usr/bin/env python3
"""
Language-detecting test runner for the GoblinBench scoring pipeline.

Auto-detects the language of a fixture and runs the appropriate test
command. Returns a score contract JSON on stdout.

Supported languages:
  - Python (pyproject.toml, pytest.ini, setup.py/setup.cfg) — pytest
  - TypeScript/JavaScript (package.json + jest/vitest/mocha config)
  - Go (go.mod) — go test ./...
  - Rust (Cargo.toml) — cargo test

Usage (via gb-score.py):
  python3 scripts/scorers/coding-tests.py --fixture-dir <path>

Standalone:
  python3 scripts/scorers/coding-tests.py --fixture-dir <path> [options]
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys


# ── Language detection ─────────────────────────────────────────────────────


def detect_language(fixture_dir: str) -> str | None:
    """Detect the primary language of the fixture."""
    f = pathlib.Path(fixture_dir)

    if (f / "pyproject.toml").exists() or (f / "pytest.ini").exists():
        return "python"
    for pat in ("setup.py", "setup.cfg"):
        if (f / pat).exists():
            return "python"

    if (f / "go.mod").exists():
        return "go"

    if (f / "Cargo.toml").exists():
        return "rust"

    package_json = f / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text())
            dev_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if any(k in dev_deps for k in ("jest", "vitest", "mocha", "ava", "tap")):
                return "typescript"
            if "scripts" in pkg and any(
                "test" in v for v in pkg["scripts"].values()
            ):
                return "typescript"
        except (json.JSONDecodeError, OSError):
            pass
        return "typescript"  # has package.json but no test dep — guess TS

    return None


# ── Test runners ───────────────────────────────────────────────────────────


def run_pytest(fixture_dir: str, timeout: int) -> dict:
    """Run pytest and parse results."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "--no-header"],
            cwd=fixture_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        return {
            "success": False, "error": f"pytest timed out after {timeout}s",
            "human_summary": "FAIL: coding-tests: pytest timed out",
            "passed": False, "score": 0.0,
        }
    except FileNotFoundError:
        return {
            "success": False, "error": "pytest not found",
            "human_summary": "FAIL: coding-tests: pytest not installed",
            "passed": False, "score": 0.0,
        }

    # Parse pytest summary line
    passed = 0
    failed = 0
    total = 0
    for line in stdout.split("\n"):
        m = re.search(r"(\d+) passed", line)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", line)
        if m:
            failed = int(m.group(1))
        # Total is implicit: passed + failed (skip/slow don't count)

    total = passed + failed
    score = passed / total if total > 0 else 0.0
    all_pass = failed == 0 and total > 0

    detail = {
        "language": "python",
        "framework": "pytest",
        "passed": passed,
        "failed": failed,
        "total": total,
        "stdout": stdout[-2000:],
    }

    return {
        "success": True,
        "score": score,
        "passed": all_pass,
        "human_summary": f"PASS" if all_pass else f"FAIL",
        "explanation": f"pytest: {passed}/{total} passed, {failed} failed",
        "detail": detail,
    }


def run_go_test(fixture_dir: str, timeout: int) -> dict:
    """Run go test ./... and parse JSON event output."""
    try:
        result = subprocess.run(
            ["go", "test", "./...", "-count=1", "-json"],
            cwd=fixture_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {
            "success": False, "error": f"go test timed out after {timeout}s",
            "human_summary": "FAIL: coding-tests: go test timed out",
            "passed": False, "score": 0.0,
        }
    except FileNotFoundError:
        return {
            "success": False, "error": "go not found",
            "human_summary": "FAIL: coding-tests: go not installed",
            "passed": False, "score": 0.0,
        }

    passed_tests: set[str] = set()
    failed_tests: set[str] = set()
    package_failed = result.returncode != 0
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        test_name = event.get("Test")
        action = event.get("Action")
        package = event.get("Package", "")
        if test_name and action == "pass":
            passed_tests.add(f"{package}::{test_name}")
        elif test_name and action == "fail":
            failed_tests.add(f"{package}::{test_name}")
        elif not test_name and action == "fail":
            package_failed = True

    # A test that eventually fails may have intermediate pass events for subtests;
    # final fail wins for scoring.
    passed_tests -= failed_tests
    passed = len(passed_tests)
    failed = len(failed_tests)
    total = passed + failed
    score = passed / total if total > 0 else (1.0 if result.returncode == 0 else 0.0)
    all_pass = result.returncode == 0 and not package_failed

    detail = {
        "language": "go",
        "framework": "go test",
        "passed": passed,
        "failed": failed,
        "total": total,
        "exit_code": result.returncode,
        "output": output[-2000:],
    }

    return {
        "success": True,
        "score": score,
        "passed": all_pass,
        "human_summary": "PASS" if all_pass else "FAIL",
        "explanation": f"go test: {passed}/{total} passed, {failed} failed (exit {result.returncode})",
        "detail": detail,
    }


def run_cargo_test(fixture_dir: str, timeout: int) -> dict:
    """Run cargo test."""
    fixture_path = pathlib.Path(fixture_dir)
    try:
        result = subprocess.run(
            ["cargo", "test", "--no-fail-fast"],
            cwd=fixture_dir,
            capture_output=True, text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {
            "success": False, "error": f"cargo test timed out after {timeout}s",
            "human_summary": "FAIL: coding-tests: cargo test timed out",
            "passed": False, "score": 0.0,
        }
    except FileNotFoundError:
        return {
            "success": False, "error": "cargo not found",
            "human_summary": "FAIL: coding-tests: cargo not installed",
            "passed": False, "score": 0.0,
        }
    finally:
        target_dir = fixture_path / "target"
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)

    # Parse lines like:
    # "test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"
    # Cargo emits one summary per test binary; sum all nonzero summaries.
    passed = 0
    failed = 0
    for line in output.split("\n"):
        if "test result:" in line:
            m_p = re.search(r"(\d+) passed", line)
            m_f = re.search(r"(\d+) failed", line)
            if m_p:
                passed += int(m_p.group(1))
            if m_f:
                failed += int(m_f.group(1))

    total = passed + failed
    score = passed / total if total > 0 else 0.0
    all_pass = result.returncode == 0 and failed == 0 and total > 0

    detail = {
        "language": "rust",
        "framework": "cargo test",
        "passed": passed,
        "failed": failed,
        "total": total,
        "output": output[-2000:],
    }

    return {
        "success": True,
        "score": score,
        "passed": all_pass,
        "human_summary": f"PASS" if all_pass else f"FAIL",
        "explanation": f"cargo test: {passed}/{total} passed, {failed} failed",
        "detail": detail,
    }


def run_npm_test(fixture_dir: str, timeout: int) -> dict:
    """Run npm test (for TypeScript/JS fixtures using jest/vitest)."""
    fixture_path = pathlib.Path(fixture_dir)
    try:
        # Try installing deps first for CI scenarios
        subprocess.run(
            ["npm", "install", "--ignore-scripts"],
            cwd=fixture_dir,
            capture_output=True, text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pass  # non-fatal — maybe deps are already installed

    try:
        result = subprocess.run(
            ["npm", "test", "--", "--no-coverage"],
            cwd=fixture_dir,
            capture_output=True, text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        exit_ok = result.returncode == 0
    except subprocess.TimeoutExpired:
        return {
            "success": False, "error": f"npm test timed out after {timeout}s",
            "human_summary": "FAIL: coding-tests: npm test timed out",
            "passed": False, "score": 0.0,
        }
    finally:
        # node_modules is a generated dependency cache, not an agent artifact.
        # Remove it after scoring so per-run fixtures don't balloon in size.
        for generated in ("node_modules", "coverage", "dist"):
            path = fixture_path / generated
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    # Parse framework-agnostic: look for common pass/fail patterns
    passed = 0
    failed = 0
    for line in output.split("\n"):
        m = re.search(r"(\d+) passed", line, re.IGNORECASE)
        if m:
            passed = max(passed, int(m.group(1)))
        m = re.search(r"(\d+) failed", line, re.IGNORECASE)
        if m:
            failed = max(failed, int(m.group(1)))

    total = passed + failed
    score = passed / total if total > 0 else (1.0 if exit_ok else 0.0)
    all_pass = exit_ok

    detail = {
        "language": "typescript",
        "framework": "npm test",
        "passed": passed,
        "failed": failed,
        "total": total,
        "exit_code": result.returncode,
        "output": output[-2000:],
    }

    return {
        "success": True,
        "score": score,
        "passed": all_pass,
        "human_summary": f"PASS" if all_pass else f"FAIL",
        "explanation": f"npm test: exit {result.returncode}",
        "detail": detail,
    }


# ── Main dispatcher ────────────────────────────────────────────────────────


LANGUAGE_RUNNERS = {
    "python": run_pytest,
    "go": run_go_test,
    "rust": run_cargo_test,
    "typescript": run_npm_test,
}


def main():
    parser = argparse.ArgumentParser(description="Language-detecting test scorer")
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--params", help="JSON-encoded scenario parameters")
    args = parser.parse_args()

    fixture_dir = args.fixture_dir

    if not os.path.isdir(fixture_dir):
        print(json.dumps({
            "scorer_id": "coding-tests",
            "scorer_name": "Coding Test Scorer",
            "scoring_kind": "script",
            "success": False,
            "error": f"Fixture directory not found: {fixture_dir}",
            "human_summary": "FAIL: coding-tests: fixture not found",
            "passed": False,
            "score": 0.0,
        }))
        return

    lang = detect_language(fixture_dir)
    if lang is None:
        print(json.dumps({
            "scorer_id": "coding-tests",
            "scorer_name": "Coding Test Scorer",
            "scoring_kind": "script",
            "success": False,
            "error": "Could not detect fixture language (no pyproject.toml, "
                     "go.mod, Cargo.toml, or package.json with test framework found)",
            "human_summary": "FAIL: coding-tests: unknown language",
            "passed": False,
            "score": 0.0,
        }))
        return

    runner = LANGUAGE_RUNNERS.get(lang)
    if runner is None:
        print(json.dumps({
            "scorer_id": "coding-tests",
            "scorer_name": "Coding Test Scorer",
            "scoring_kind": "script",
            "success": False,
            "error": f"No test runner implemented for '{lang}'",
            "human_summary": f"FAIL: coding-tests: unsupported language '{lang}'",
            "passed": False,
            "score": 0.0,
        }))
        return

    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError:
            pass

    timeout = params.get("timeout_seconds", 120)
    if isinstance(timeout, str):
        timeout = int(timeout)

    result = runner(fixture_dir, timeout)

    # Apply threshold if not already passed/failed properly
    threshold = args.threshold
    if result.get("passed") is None and result.get("score") is not None:
        result["passed"] = result["score"] >= threshold

    # Ensure required fields
    result.setdefault("scorer_id", "coding-tests")
    result.setdefault("scorer_name", "Coding Test Scorer")
    result.setdefault("scoring_kind", "script")

    # Write artifact if requested
    if args.artifact_dir and result.get("success"):
        artifact = pathlib.Path(args.artifact_dir)
        artifact.mkdir(parents=True, exist_ok=True)
        with open(artifact / "coding-tests.json", "w") as f:
            json.dump(result.get("detail", {}), f, indent=2)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
