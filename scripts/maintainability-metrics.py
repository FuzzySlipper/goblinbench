#!/usr/bin/env python3
"""Maintainability-pressure metrics for GoblinBench coding fixtures.

This scorer compares a completed mini-service fixture against a baseline snapshot
stored inside the fixture. It focuses on architectural pressure signals: central
file growth, changed-file concentration, largest function growth, setup/handler
thickness, public API expansion, import fan-out, and comment/readability hints.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", "dist", "coverage", "target"}
DEFAULT_SOURCE_ROOT = "service"
DEFAULT_BASELINE_PATH = ".goblinbench/maintainability-baseline.json"
GENERIC_NAMES = {
    "data", "item", "items", "thing", "things", "obj", "objs", "tmp", "temp",
    "val", "vals", "value", "values", "result", "results", "res", "resp",
    "handler", "process", "do", "run", "main", "helper", "manager", "utils",
}
RESTATEMENT_PATTERNS = [
    re.compile(r"^\s*#\s*(loop|iterate)\b", re.I),
    re.compile(r"^\s*#\s*(return|returns)\b", re.I),
    re.compile(r"^\s*#\s*(create|creates)\b", re.I),
    re.compile(r"^\s*#\s*(check|checks)\b", re.I),
    re.compile(r"^\s*#\s*(increment|decrement|set|get)\b", re.I),
]
SEMANTIC_COMMENT_HINTS = {
    "because", "so that", "preserve", "avoid", "invariant", "contract", "compat",
    "clock", "boundary", "duplicate", "audit", "security", "permission", "idempotent",
}


@dataclass
class FunctionMetric:
    name: str
    lineno: int
    end_lineno: int
    body_lines: int
    max_nesting: int
    branch_count: int
    is_public: bool
    has_docstring: bool


@dataclass
class FileMetric:
    path: str
    sha256: str
    loc: int
    comments: int
    restatement_comments: int
    semantic_comments: int
    imports: int
    public_api_count: int
    function_count: int
    class_count: int
    functions: list[dict[str, Any]]
    identifiers: list[str]
    magic_literals: int


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def should_skip(path: Path) -> bool:
    return bool(set(path.parts) & SKIP_DIRS)


def collect_source_files(root: Path, source_root: str) -> list[Path]:
    base = root / source_root
    if not base.exists():
        return []
    files: list[Path] = []
    for path in base.rglob("*.py"):
        if should_skip(path.relative_to(root)):
            continue
        if path.name == "__init__.py":
            continue
        files.append(path)
    return sorted(files)


def count_loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def comment_metrics(text: str) -> tuple[int, int, int]:
    comments = 0
    restatement = 0
    semantic = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        comments += 1
        body = stripped.lstrip("#").strip().lower()
        if any(pattern.search(stripped) for pattern in RESTATEMENT_PATTERNS):
            restatement += 1
        if any(hint in body for hint in SEMANTIC_COMMENT_HINTS):
            semantic += 1
    return comments, restatement, semantic


def max_nesting_and_branches(node: ast.AST) -> tuple[int, int]:
    branch_nodes = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Match, ast.BoolOp)
    branches = 0
    max_depth = 0

    def walk(current: ast.AST, depth: int) -> None:
        nonlocal branches, max_depth
        is_branch = isinstance(current, branch_nodes)
        next_depth = depth + 1 if is_branch else depth
        if is_branch:
            branches += 1
            max_depth = max(max_depth, next_depth)
        for child in ast.iter_child_nodes(current):
            walk(child, next_depth)

    walk(node, 0)
    return max_depth, branches


def collect_identifiers(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
    return names


def count_magic_literals(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, str):
                if len(value) >= 3 and value not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    count += 1
            elif isinstance(value, (int, float)) and value not in {0, 1, 200, 201, 400, 403, 404, 409, 501}:
                count += 1
    return count


def analyse_file(path: Path, root: Path) -> FileMetric:
    text = read_text(path)
    tree = ast.parse(text, filename=str(path))
    funcs: list[dict[str, Any]] = []
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno or node.lineno
        max_nesting, branches = max_nesting_and_branches(node)
        funcs.append(asdict(FunctionMetric(
            name=node.name,
            lineno=node.lineno,
            end_lineno=end,
            body_lines=max(0, end - node.lineno),
            max_nesting=max_nesting,
            branch_count=branches,
            is_public=not node.name.startswith("_"),
            has_docstring=ast.get_docstring(node) is not None,
        )))
    comments, restatement, semantic = comment_metrics(text)
    imports = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
    public_api = sum(1 for f in funcs if f["is_public"]) + sum(1 for c in classes if not c.name.startswith("_"))
    return FileMetric(
        path=rel(path, root),
        sha256=sha256_text(text),
        loc=count_loc(text),
        comments=comments,
        restatement_comments=restatement,
        semantic_comments=semantic,
        imports=imports,
        public_api_count=public_api,
        function_count=len(funcs),
        class_count=len(classes),
        functions=funcs,
        identifiers=collect_identifiers(tree),
        magic_literals=count_magic_literals(tree),
    )


def aggregate(files: list[FileMetric], central_paths: set[str], setup_paths: set[str], handler_paths: set[str]) -> dict[str, Any]:
    file_dict = {f.path: asdict(f) for f in files}
    locs = [f.loc for f in files]
    all_functions = [fn for f in files for fn in f.functions]
    function_lines = [fn["body_lines"] for fn in all_functions]
    identifiers = [ident for f in files for ident in f.identifiers]
    meaningful_identifiers = [ident for ident in identifiers if len(ident) > 2 and ident not in GENERIC_NAMES]
    generic_identifiers = [ident for ident in identifiers if ident in GENERIC_NAMES or len(ident) <= 2]

    def max_func_for(paths: set[str] | None = None, name_contains: tuple[str, ...] = ()) -> int:
        funcs = []
        for f in files:
            if paths is not None and f.path not in paths:
                continue
            for fn in f.functions:
                if name_contains and not any(token in fn["name"] for token in name_contains):
                    continue
                funcs.append(fn["body_lines"])
        return max(funcs) if funcs else 0

    public_funcs = [fn for fn in all_functions if fn["is_public"]]
    documented_public_funcs = [fn for fn in public_funcs if fn["has_docstring"]]
    total_comments = sum(f.comments for f in files)
    restatement_comments = sum(f.restatement_comments for f in files)
    semantic_comments = sum(f.semantic_comments for f in files)

    total_loc = sum(locs)
    central_loc = sum(f.loc for f in files if f.path in central_paths)
    max_file_share = max(locs) / total_loc if total_loc else 0.0

    return {
        "source_files": len(files),
        "total_loc": total_loc,
        "max_file_loc": max(locs) if locs else 0,
        "max_file_share": round(max_file_share, 4),
        "central_loc": central_loc,
        "central_loc_share": round(central_loc / total_loc, 4) if total_loc else 0.0,
        "total_functions": len(all_functions),
        "public_api_count": sum(f.public_api_count for f in files),
        "import_total": sum(f.imports for f in files),
        "magic_literal_total": sum(f.magic_literals for f in files),
        "largest_function_lines": max(function_lines) if function_lines else 0,
        "mean_function_lines": round(statistics.mean(function_lines), 1) if function_lines else 0.0,
        "max_function_nesting": max((fn["max_nesting"] for fn in all_functions), default=0),
        "max_function_branches": max((fn["branch_count"] for fn in all_functions), default=0),
        "max_handler_function_lines": max_func_for(handler_paths),
        "max_setup_function_lines": max_func_for(setup_paths, ("build", "setup", "create", "container")),
        "public_doc_coverage": round(len(documented_public_funcs) / len(public_funcs), 4) if public_funcs else 0.0,
        "comment_total": total_comments,
        "restatement_comment_ratio": round(restatement_comments / total_comments, 4) if total_comments else 0.0,
        "semantic_comment_ratio": round(semantic_comments / total_comments, 4) if total_comments else 0.0,
        "identifier_count": len(identifiers),
        "meaningful_identifier_ratio": round(len(meaningful_identifiers) / len(identifiers), 4) if identifiers else 0.0,
        "generic_identifier_ratio": round(len(generic_identifiers) / len(identifiers), 4) if identifiers else 0.0,
        "files": file_dict,
    }


def build_snapshot(root: Path, source_root: str, central_paths: set[str], setup_paths: set[str], handler_paths: set[str]) -> dict[str, Any]:
    files = [analyse_file(path, root) for path in collect_source_files(root, source_root)]
    return {
        "version": 1,
        "source_root": source_root,
        "central_paths": sorted(central_paths),
        "setup_paths": sorted(setup_paths),
        "handler_paths": sorted(handler_paths),
        "summary": aggregate(files, central_paths, setup_paths, handler_paths),
    }


def compute_deltas(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    cur_summary = current["summary"]
    base_summary = baseline["summary"]
    cur_files = cur_summary["files"]
    base_files = base_summary["files"]
    paths = sorted(set(cur_files) | set(base_files))
    changed_paths = []
    changed_mass: dict[str, int] = {}
    line_deltas: dict[str, int] = {}
    for path in paths:
        cur = cur_files.get(path)
        base = base_files.get(path)
        if cur is None:
            changed_paths.append(path)
            changed_mass[path] = base.get("loc", 0)
            line_deltas[path] = -base.get("loc", 0)
        elif base is None:
            changed_paths.append(path)
            changed_mass[path] = cur.get("loc", 0)
            line_deltas[path] = cur.get("loc", 0)
        elif cur.get("sha256") != base.get("sha256"):
            changed_paths.append(path)
            changed_mass[path] = max(cur.get("loc", 0), abs(cur.get("loc", 0) - base.get("loc", 0)), 1)
            line_deltas[path] = cur.get("loc", 0) - base.get("loc", 0)

    total_changed_mass = sum(changed_mass.values())
    max_changed_file_share = max(changed_mass.values()) / total_changed_mass if total_changed_mass else 0.0
    central_paths = set(current.get("central_paths", []))
    setup_paths = set(current.get("setup_paths", []))
    handler_paths = set(current.get("handler_paths", []))
    central_changed_mass = sum(mass for path, mass in changed_mass.items() if path in central_paths)

    delta_keys = [
        "total_loc", "max_file_loc", "max_file_share", "central_loc", "central_loc_share",
        "total_functions", "public_api_count", "import_total", "magic_literal_total",
        "largest_function_lines", "mean_function_lines", "max_function_nesting", "max_function_branches",
        "max_handler_function_lines", "max_setup_function_lines", "public_doc_coverage",
        "comment_total", "restatement_comment_ratio", "semantic_comment_ratio",
        "meaningful_identifier_ratio", "generic_identifier_ratio",
    ]
    summary_delta = {
        key: round(cur_summary.get(key, 0) - base_summary.get(key, 0), 4)
        for key in delta_keys
    }

    return {
        "changed_files": changed_paths,
        "changed_file_count": len(changed_paths),
        "changed_line_mass": total_changed_mass,
        "changed_file_mass": changed_mass,
        "line_deltas": line_deltas,
        "max_changed_file_share": round(max_changed_file_share, 4),
        "central_changed_mass_share": round(central_changed_mass / total_changed_mass, 4) if total_changed_mass else 0.0,
        "central_line_deltas": {path: line_deltas.get(path, 0) for path in sorted(central_paths)},
        "setup_line_deltas": {path: line_deltas.get(path, 0) for path in sorted(setup_paths)},
        "handler_line_deltas": {path: line_deltas.get(path, 0) for path in sorted(handler_paths)},
        "summary_delta": summary_delta,
    }


def run_metrics(
    fixture_dir: str,
    *,
    source_root: str = DEFAULT_SOURCE_ROOT,
    baseline_path: str = DEFAULT_BASELINE_PATH,
    central_paths: list[str] | None = None,
    setup_paths: list[str] | None = None,
    handler_paths: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(fixture_dir)
    central = set(central_paths or ["service/router.py", "service/container.py", "service/handlers/customers.py"])
    setup = set(setup_paths or ["service/container.py"])
    handlers = set(handler_paths or ["service/handlers/customers.py"])
    current = build_snapshot(root, source_root, central, setup, handlers)
    baseline_file = root / baseline_path
    baseline = json.loads(baseline_file.read_text(encoding="utf-8")) if baseline_file.exists() else None
    result = {"current": current["summary"], "baseline_available": baseline is not None}
    if baseline is not None:
        result["baseline"] = baseline["summary"]
        result["deltas"] = compute_deltas(current, baseline)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintainability-pressure metrics")
    parser.add_argument("fixture_dir")
    parser.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--baseline-path", default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--central-path", action="append", dest="central_paths")
    parser.add_argument("--setup-path", action="append", dest="setup_paths")
    parser.add_argument("--handler-path", action="append", dest="handler_paths")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()

    root = Path(args.fixture_dir)
    central = set(args.central_paths or ["service/router.py", "service/container.py", "service/handlers/customers.py"])
    setup = set(args.setup_paths or ["service/container.py"])
    handlers = set(args.handler_paths or ["service/handlers/customers.py"])
    if args.write_baseline:
        snapshot = build_snapshot(root, args.source_root, central, setup, handlers)
        baseline_file = root / args.baseline_path
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        print(f"baseline written to {baseline_file}")
        return

    metrics = run_metrics(
        args.fixture_dir,
        source_root=args.source_root,
        baseline_path=args.baseline_path,
        central_paths=args.central_paths,
        setup_paths=args.setup_paths,
        handler_paths=args.handler_paths,
    )
    if args.output:
        Path(args.output).write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
