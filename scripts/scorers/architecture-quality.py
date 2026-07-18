#!/usr/bin/env python3
"""Configurable architectural-quality scorer for hard coding fixtures.

Behavior stays with ``coding-tests``. This scorer turns maintainability deltas,
dependency direction, seam usage, and duplication into a separate bounded score
so reports do not conflate correct behavior with clean architecture.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "architecture_quality_metrics",
    SCRIPT_DIR / "maintainability-metrics.py",
)
if spec is None or spec.loader is None:
    raise RuntimeError("could not import maintainability-metrics.py")
metrics_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = metrics_mod
spec.loader.exec_module(metrics_mod)

SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}
IMPORT_PATTERN = re.compile(
    r"(?:from\s+['\"](?P<ts>[^'\"]+)['\"]|"
    r"require\(['\"](?P<require>[^'\"]+)['\"]\)|"
    r"\buse\s+(?P<rust>[A-Za-z0-9_:]+))"
)


def _source_files(root: Path, source_root: str) -> list[Path]:
    base = root / source_root
    return sorted(
        path for path in base.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_EXTENSIONS
        and not path.name.endswith((".d.ts", "_test.go"))
    )


def _dependency_violations(
    root: Path,
    files: list[Path],
    rules: list[dict[str, Any]],
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        imports = [next(value for value in match.groups() if value is not None) for match in IMPORT_PATTERN.finditer(text)]
        for rule in rules:
            if not fnmatch.fnmatch(relative, str(rule.get("from", ""))):
                continue
            for imported in imports:
                for forbidden in rule.get("forbid", []):
                    if re.search(str(forbidden), imported):
                        violations.append({
                            "file": relative,
                            "import": imported,
                            "forbidden": str(forbidden),
                        })
    return violations


def _normalized_line(line: str) -> str | None:
    stripped = line.strip()
    if (
        len(stripped) < 20
        or stripped in {"{", "}", "};", ");"}
        or stripped.startswith(("//", "#", "/*", "*", "import ", "use "))
    ):
        return None
    normalized = re.sub(r"\s+", " ", stripped)
    normalized = re.sub(r"['\"][^'\"]*['\"]", "<string>", normalized)
    normalized = re.sub(r"\b\d+\b", "<number>", normalized)
    return normalized


def _duplication(files: list[Path], root: Path) -> dict[str, Any]:
    owners: dict[str, set[str]] = {}
    total = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = _normalized_line(raw_line)
            if line is None:
                continue
            total += 1
            owners.setdefault(line, set()).add(relative)
    duplicated = {line: sorted(paths) for line, paths in owners.items() if len(paths) > 1}
    duplicated_occurrences = sum(len(paths) for paths in duplicated.values())
    return {
        "eligible_line_count": total,
        "duplicated_occurrence_count": duplicated_occurrences,
        "cross_file_ratio": round(duplicated_occurrences / total, 4) if total else 0.0,
        "samples": [
            {"line": line[:160], "files": paths}
            for line, paths in list(sorted(duplicated.items()))[:12]
        ],
    }


def score_architecture(root: Path, params: dict[str, Any], threshold: float) -> dict[str, Any]:
    source_root = str(params.get("source_root", "src"))
    baseline_path = str(params.get("baseline_path", ".goblinbench/maintainability-baseline.json"))
    central_paths = [str(value) for value in params.get("central_paths", [])]
    handler_paths = [str(value) for value in params.get("handler_paths", central_paths)]
    setup_paths = [str(value) for value in params.get("setup_paths", [])]
    metrics = metrics_mod.run_metrics(
        str(root),
        source_root=source_root,
        baseline_path=baseline_path,
        central_paths=central_paths,
        setup_paths=setup_paths,
        handler_paths=handler_paths,
    )
    if not metrics.get("baseline_available"):
        raise ValueError(f"architecture baseline not found: {baseline_path}")

    files = _source_files(root, source_root)
    dependency_violations = _dependency_violations(
        root, files, list(params.get("dependency_rules", []))
    )
    duplication = _duplication(files, root)
    deltas = metrics.get("deltas", {})
    current = metrics.get("current", {})
    gates = params.get("gates", {})
    changed_file_count = int(deltas.get("changed_file_count", 0))
    central_share = float(deltas.get("central_changed_mass_share", 0.0))
    handler_lines = int(current.get("max_handler_function_lines", 0))
    duplication_ratio = float(duplication["cross_file_ratio"])

    penalties: list[dict[str, Any]] = []

    def penalize(gate: str, observed: Any, limit: Any, weight: float) -> None:
        penalties.append({"gate": gate, "observed": observed, "limit": limit, "penalty": weight})

    min_changed_files = int(gates.get("min_changed_files", 1))
    if changed_file_count and changed_file_count < min_changed_files:
        penalize("seam-preservation", changed_file_count, min_changed_files, 0.2)
    max_central_share = float(gates.get("max_central_changed_mass_share", 0.8))
    if central_share > max_central_share:
        penalize("centralization", central_share, max_central_share, 0.25)
    max_handler_lines = int(gates.get("max_handler_function_lines", 90))
    if handler_lines > max_handler_lines:
        penalize("largest-central-function", handler_lines, max_handler_lines, 0.2)
    max_duplication_ratio = float(gates.get("max_cross_file_duplication_ratio", 0.12))
    if duplication_ratio > max_duplication_ratio:
        penalize("cross-file-duplication", duplication_ratio, max_duplication_ratio, 0.15)
    if dependency_violations:
        penalize(
            "dependency-direction",
            len(dependency_violations),
            0,
            min(0.3, 0.1 * len(dependency_violations)),
        )

    score = round(max(0.0, 1.0 - sum(float(item["penalty"]) for item in penalties)), 4)
    passed = score >= threshold
    gold_path = root / str(params.get("gold_path", ".goblinbench/architecture.md"))
    detail = {
        "changed_file_count": changed_file_count,
        "central_changed_mass_share": central_share,
        "max_handler_function_lines": handler_lines,
        "dependency_violations": dependency_violations,
        "duplication": duplication,
        "penalties": penalties,
        "maintainability": metrics,
        "gold_expectations_present": gold_path.is_file(),
    }
    summary = (
        f"{'PASS' if passed else 'PENALTY'}: architecture {score:.2f}; "
        f"{changed_file_count} changed files, central {central_share:.0%}, "
        f"largest central fn {handler_lines} LOC, {len(dependency_violations)} direction violations"
    )
    return {
        "scorer_id": "architecture-quality",
        "scorer_name": "Architecture Quality",
        "scoring_kind": "heuristic",
        "success": True,
        "score": score,
        "passed": passed,
        "threshold": threshold,
        "human_summary": summary,
        "explanation": "Architectural penalties are reported separately from deterministic behavior tests.",
        "detail": detail,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Architecture quality scorer")
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--params")
    args = parser.parse_args()
    try:
        params = json.loads(args.params) if args.params else {}
        result = score_architecture(Path(args.fixture_dir), params, args.threshold)
    except Exception as error:  # noqa: BLE001
        result = {
            "scorer_id": "architecture-quality",
            "scorer_name": "Architecture Quality",
            "scoring_kind": "heuristic",
            "success": False,
            "passed": False,
            "score": 0.0,
            "human_summary": f"FAIL: architecture-quality: {error}",
            "error": str(error),
        }
    if args.artifact_dir and result.get("success"):
        artifact = Path(args.artifact_dir)
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "architecture-quality.json").write_text(
            json.dumps(result.get("detail", {}), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
