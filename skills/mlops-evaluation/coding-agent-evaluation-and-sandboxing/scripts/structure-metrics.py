#!/usr/bin/env python3
"""
structure-metrics — structural analysis scorer for coding style probes.

Measures the structural properties of a completed implementation directory
(fixed interfaces + agent-filled bodies) and emits a metrics JSON record.

Usage:
    python3 scripts/structure-metrics.py <implementation_dir> [--output results.json]

Metrics emitted:
  - total_files: count of .py files (excluding tests)
  - total_lines: total LOC across all impl files
  - loc_per_file: list[int], one per impl file
  - functions: total function count (excluding tests)
  - lines_per_function: distribution (min, max, mean, p95)
  - type_annotation_depth: fraction of function params + returns with type hints
  - docstring_coverage: fraction of functions with a docstring
  - test_to_source_ratio: test_lines / impl_lines
  - try_except_count: total try/except blocks in impl files
  - import_count: total import statements in impl files

Installation: copy to goblinbench/scripts/ ; no deps beyond stdlib.
"""

import argparse
import ast
import json
import os
import pathlib
import statistics
import sys


def count_lines(filepath: str) -> int:
    with open(filepath) as f:
        return sum(1 for _ in f)


def analyse_impl_file(filepath: str) -> dict:
    """Return structural metrics for one implementation file."""
    tree = ast.parse(open(filepath).read(), filename=filepath)
    lines = count_lines(filepath)

    functions = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    func_metrics = []
    for fn in functions:
        body_lines = (fn.end_lineno or fn.lineno) - fn.lineno
        has_docstring = (
            fn.body
            and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)
        )
        typed_params = 0
        total_params = 0
        for arg in fn.args.args + fn.args.kwonlyargs:
            total_params += 1
            if arg.annotation:
                typed_params += 1
        has_return_hint = fn.returns is not None

        func_metrics.append({
            "name": fn.name,
            "body_lines": body_lines,
            "has_docstring": has_docstring,
            "typed_params": typed_params,
            "total_params": total_params,
            "has_return_hint": has_return_hint,
        })

    try_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Try))
    import_count = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
    )

    return {
        "path": str(filepath),
        "lines": lines,
        "function_count": len(functions),
        "functions": func_metrics,
        "try_except_count": try_count,
        "import_count": import_count,
    }


def analyse_test_file(filepath: str) -> dict:
    lines = count_lines(filepath)
    tree = ast.parse(open(filepath).read(), filename=filepath)
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    return {
        "path": str(filepath),
        "lines": lines,
        "test_function_count": len(functions),
    }


def collect_impl_files(root: str) -> list[str]:
    impl_files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            if fn.startswith("test_") or fn == "__init__.py":
                continue
            impl_files.append(os.path.join(dirpath, fn))
    return sorted(impl_files)


def collect_test_files(root) -> list[str]:
    test_files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.startswith("test_") and fn.endswith(".py"):
                test_files.append(os.path.join(dirpath, fn))
    return sorted(test_files)


def compute_docstring_coverage(func_metrics: list[dict]) -> float:
    if not func_metrics:
        return 0.0
    return sum(1 for f in func_metrics if f["has_docstring"]) / len(func_metrics)


def compute_type_depth(func_metrics: list[dict]) -> float:
    total = 0
    typed = 0
    for f in func_metrics:
        total += f["total_params"] + 1
        typed += f["typed_params"] + (1 if f["has_return_hint"] else 0)
    if total == 0:
        return 0.0
    return typed / total


def run_metrics(impl_dir: str) -> dict:
    impl_files = collect_impl_files(impl_dir)
    test_files = collect_test_files(impl_dir)

    impl_results = [analyse_impl_file(f) for f in impl_files]
    test_results = [analyse_test_file(f) for f in test_files]

    all_funcs = []
    for r in impl_results:
        all_funcs.extend(r["functions"])

    body_lines = [f["body_lines"] for f in all_funcs] if all_funcs else [0]

    total_impl_lines = sum(r["lines"] for r in impl_results)
    total_test_lines = sum(r["lines"] for r in test_results)

    total_imports = sum(r["import_count"] for r in impl_results)
    total_try = sum(r["try_except_count"] for r in impl_results)

    return {
        "total_impl_files": len(impl_files),
        "total_test_files": len(test_files),
        "total_impl_lines": total_impl_lines,
        "total_test_lines": total_test_lines,
        "loc_per_file": [r["lines"] for r in impl_results],
        "total_functions": len(all_funcs),
        "functions_per_file": [r["function_count"] for r in impl_results],
        "lines_per_function": {
            "min": min(body_lines),
            "max": max(body_lines),
            "mean": round(statistics.mean(body_lines), 1) if len(body_lines) > 1 else float(body_lines[0]),
            "p95": round(sorted(body_lines)[int(len(body_lines) * 0.95)], 1) if len(body_lines) > 1 else float(body_lines[0]),
        },
        "docstring_coverage": round(compute_docstring_coverage(all_funcs), 4),
        "type_annotation_depth": round(compute_type_depth(all_funcs), 4),
        "test_to_source_ratio": round(total_test_lines / total_impl_lines, 4) if total_impl_lines > 0 else 0.0,
        "try_except_total": total_try,
        "import_total": total_imports,
    }


def main():
    parser = argparse.ArgumentParser(description="Structure metrics scorer")
    parser.add_argument("impl_dir", help="Path to implementation directory")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()

    if not os.path.isdir(args.impl_dir):
        print(f"ERROR: not a directory: {args.impl_dir}", file=sys.stderr)
        sys.exit(1)

    metrics = run_metrics(args.impl_dir)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics written to {args.output}")
    else:
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
