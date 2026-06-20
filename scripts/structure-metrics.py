#!/usr/bin/env python3
"""
structure-metrics — structural analysis scorer for coding style probes.

Measures structural properties of completed implementation directories
(fixed interfaces + agent-filled bodies) and emits a metrics JSON record.

Supports:
  - Python via ast
  - TypeScript/JavaScript via lightweight text parsing
  - Go via lightweight text parsing
  - Rust via lightweight text parsing

Usage:
    python3 scripts/structure-metrics.py <implementation_dir> [--output results.json]
"""

import argparse
import ast
import json
import os
import re
import statistics
import sys

SKIP_DIRS = {"node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".git"}
PY_IMPL_EXTS = {".py"}
TS_IMPL_EXTS = {".ts", ".tsx", ".js", ".jsx"}
GO_IMPL_EXTS = {".go"}
RUST_IMPL_EXTS = {".rs"}
ALL_EXTS = PY_IMPL_EXTS | TS_IMPL_EXTS | GO_IMPL_EXTS | RUST_IMPL_EXTS


def count_lines(filepath: str) -> int:
    with open(filepath, encoding="utf-8") as f:
        return sum(1 for _ in f)


def read_text(filepath: str) -> str:
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def analyse_python_impl_file(filepath: str) -> dict:
    """Return structural metrics for one Python implementation file."""
    tree = ast.parse(read_text(filepath), filename=filepath)
    lines = count_lines(filepath)

    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

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
    import_count = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))

    return {
        "path": str(filepath),
        "lines": lines,
        "function_count": len(functions),
        "functions": func_metrics,
        "try_except_count": try_count,
        "import_count": import_count,
    }


def _find_matching_brace(text: str, open_index: int) -> int:
    """Find the matching closing brace for a JS/TS function body."""
    depth = 0
    in_string = None
    escaped = False
    in_line_comment = False
    in_block_comment = False

    i = open_index
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in {'"', "'", "`"}:
            in_string = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text) - 1


def _line_no_at(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _has_jsdoc_before(text: str, start: int) -> bool:
    prefix = text[:start]
    # Look at the last non-empty/comment-adjacent chunk before the function.
    tail = prefix[-500:]
    return bool(re.search(r"/\*\*[\s\S]*?\*/\s*$", tail))


def _split_params(params: str) -> list[str]:
    params = params.strip()
    if not params:
        return []
    # Good enough for these probes: avoid splitting inside one-level generics/objects.
    parts = []
    depth = 0
    current = []
    for ch in params:
        if ch in "<{([":
            depth += 1
        elif ch in ">})]" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(ch)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _ts_function_metrics(text: str) -> list[dict]:
    """Extract approximate function metrics from TS/JS text."""
    patterns = [
        re.compile(
            r"(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
            r"(?:<[^>{}]*>)?\s*\((?P<params>[^)]*)\)\s*(?P<ret>:\s*[^=;{]+)?\s*\{",
            re.MULTILINE,
        ),
        re.compile(
            r"(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
            r"(?P<var_ann>:\s*[^=]+)?=\s*(?:async\s*)?(?:<[^>{}]*>\s*)?"
            r"\((?P<params>[^)]*)\)\s*(?P<ret>:\s*[^=;{]+)?\s*=>\s*\{",
            re.MULTILINE,
        ),
    ]
    matches = []
    for pattern in patterns:
        matches.extend(pattern.finditer(text))
    matches.sort(key=lambda m: m.start())

    metrics = []
    seen_spans = set()
    for m in matches:
        if m.span() in seen_spans:
            continue
        seen_spans.add(m.span())
        open_index = text.find("{", m.end() - 1)
        if open_index < 0:
            continue
        close_index = _find_matching_brace(text, open_index)
        start_line = _line_no_at(text, m.start())
        end_line = _line_no_at(text, close_index)
        params = _split_params(m.group("params") or "")
        typed_params = sum(1 for p in params if ":" in p)
        has_return_hint = bool((m.groupdict().get("ret") or "").strip())
        if not has_return_hint and m.groupdict().get("var_ann"):
            # const f: (...) => Ret = (...) => { ... }
            has_return_hint = "=>" in (m.groupdict().get("var_ann") or "")
        metrics.append({
            "name": m.group("name"),
            "body_lines": max(0, end_line - start_line),
            "has_docstring": _has_jsdoc_before(text, m.start()),
            "typed_params": typed_params,
            "total_params": len(params),
            "has_return_hint": has_return_hint,
        })
    return metrics


def analyse_ts_impl_file(filepath: str) -> dict:
    """Return lightweight text-based metrics for one TS/JS implementation file."""
    text = read_text(filepath)
    lines = count_lines(filepath)
    functions = _ts_function_metrics(text)
    try_count = len(re.findall(r"\btry\s*\{", text))
    import_count = len(re.findall(r"^\s*import\b", text, re.MULTILINE))
    return {
        "path": str(filepath),
        "lines": lines,
        "function_count": len(functions),
        "functions": functions,
        "try_except_count": try_count,
        "import_count": import_count,
    }


def _has_go_doc_before(text: str, start: int) -> bool:
    prefix = text[:start]
    tail = prefix[-500:]
    return bool(re.search(r"(?:^|\n)\s*(?://[^\n]*\n\s*)+$", tail)) or bool(
        re.search(r"/\*[\s\S]*?\*/\s*$", tail)
    )


def _go_split_params(params: str) -> list[str]:
    params = params.strip()
    if not params:
        return []
    parts = []
    depth = 0
    current = []
    for ch in params:
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(ch)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _go_param_count(params: str) -> tuple[int, int]:
    """Return typed/total param counts for a Go parameter list."""
    total = 0
    typed = 0
    for part in _go_split_params(params):
        fields = part.split()
        if len(fields) >= 2:
            # a, b int counts as 2 typed params; a int counts as 1.
            names = [n.strip() for n in " ".join(fields[:-1]).split(",") if n.strip()]
            count = max(1, len(names))
            total += count
            typed += count
        elif len(fields) == 1:
            # Anonymous parameter with only a type.
            total += 1
            typed += 1
    return typed, total


def _go_function_metrics(text: str) -> list[dict]:
    pattern = re.compile(
        r"^\s*func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\((?P<params>[^)]*)\)\s*(?P<ret>\([^)]*\)|[A-Za-z_\*\[\]\.][^{\n]*)?\s*\{",
        re.MULTILINE,
    )
    metrics = []
    for m in pattern.finditer(text):
        open_index = text.find("{", m.end() - 1)
        if open_index < 0:
            continue
        close_index = _find_matching_brace(text, open_index)
        start_line = _line_no_at(text, m.start())
        end_line = _line_no_at(text, close_index)
        typed_params, total_params = _go_param_count(m.group("params") or "")
        ret = (m.group("ret") or "").strip()
        metrics.append({
            "name": m.group("name"),
            "body_lines": max(0, end_line - start_line),
            "has_docstring": _has_go_doc_before(text, m.start()),
            "typed_params": typed_params,
            "total_params": total_params,
            "has_return_hint": bool(ret),
        })
    return metrics


def analyse_go_impl_file(filepath: str) -> dict:
    """Return lightweight text-based metrics for one Go implementation file."""
    text = read_text(filepath)
    lines = count_lines(filepath)
    functions = _go_function_metrics(text)
    error_handling_count = len(re.findall(r"if\s+err\s*!=\s*nil\s*\{", text))
    import_count = len(re.findall(r"^\s*import\b", text, re.MULTILINE))
    return {
        "path": str(filepath),
        "lines": lines,
        "function_count": len(functions),
        "functions": functions,
        "try_except_count": error_handling_count,
        "import_count": import_count,
    }


def _has_rust_doc_before(text: str, start: int) -> bool:
    prefix = text[:start]
    tail = prefix[-500:]
    return bool(re.search(r"(?:^|\n)\s*(?:///[^^\n]*\n\s*)+$", tail)) or bool(
        re.search(r"/\*\*[\s\S]*?\*/\s*$", tail)
    )


def _rust_param_count(params: str) -> tuple[int, int]:
    typed = 0
    total = 0
    for part in _split_params(params):
        part = part.strip()
        if not part or part in {"&self", "self", "&mut self", "mut self"}:
            continue
        total += 1
        if ":" in part:
            typed += 1
    return typed, total


def _rust_function_metrics(text: str) -> list[dict]:
    pattern = re.compile(
        r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>{}]*>)?\s*"
        r"\((?P<params>[^)]*)\)\s*(?P<ret>->\s*[^\{\n]+)?\s*\{",
        re.MULTILINE,
    )
    metrics = []
    for m in pattern.finditer(text):
        open_index = text.find("{", m.end() - 1)
        if open_index < 0:
            continue
        close_index = _find_matching_brace(text, open_index)
        start_line = _line_no_at(text, m.start())
        end_line = _line_no_at(text, close_index)
        typed_params, total_params = _rust_param_count(m.group("params") or "")
        metrics.append({
            "name": m.group("name"),
            "body_lines": max(0, end_line - start_line),
            "has_docstring": _has_rust_doc_before(text, m.start()),
            "typed_params": typed_params,
            "total_params": total_params,
            "has_return_hint": bool((m.group("ret") or "").strip()),
        })
    return metrics


def analyse_rust_impl_file(filepath: str) -> dict:
    """Return lightweight text-based metrics for one Rust implementation file."""
    text = read_text(filepath)
    lines = count_lines(filepath)
    functions = _rust_function_metrics(text)
    error_handling_count = len(re.findall(r"\b(?:unwrap|expect|match\s+[^\{]*\{|if\s+let\s+Err)\b", text))
    import_count = len(re.findall(r"^\s*use\s+", text, re.MULTILINE))
    return {
        "path": str(filepath),
        "lines": lines,
        "function_count": len(functions),
        "functions": functions,
        "try_except_count": error_handling_count,
        "import_count": import_count,
    }


def analyse_impl_file(filepath: str) -> dict:
    _, ext = os.path.splitext(filepath)
    if ext in PY_IMPL_EXTS:
        return analyse_python_impl_file(filepath)
    if ext in TS_IMPL_EXTS:
        return analyse_ts_impl_file(filepath)
    if ext in GO_IMPL_EXTS:
        return analyse_go_impl_file(filepath)
    if ext in RUST_IMPL_EXTS:
        return analyse_rust_impl_file(filepath)
    raise ValueError(f"unsupported implementation file extension: {filepath}")


def analyse_test_file(filepath: str) -> dict:
    """Return minimal metrics for a test file."""
    text = read_text(filepath)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    _, ext = os.path.splitext(filepath)
    if ext in PY_IMPL_EXTS:
        tree = ast.parse(text, filename=filepath)
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        count = len(functions)
    elif ext in GO_IMPL_EXTS:
        count = len(re.findall(r"^\s*func\s+Test[A-Za-z0-9_]*\s*\(", text, re.MULTILINE))
    elif ext in RUST_IMPL_EXTS:
        count = len(re.findall(r"^\s*#\[test\]", text, re.MULTILINE))
    else:
        count = len(re.findall(r"\b(?:test|it)\s*\(", text))
    return {"path": str(filepath), "lines": lines, "test_function_count": count}


def _should_skip_dir(dirpath: str) -> bool:
    parts = set(os.path.normpath(dirpath).split(os.sep))
    return bool(parts & SKIP_DIRS)


def collect_impl_files(root: str) -> list[str]:
    """Find implementation files, excluding tests, fixed type/interface files, and generated dirs."""
    impl_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if _should_skip_dir(dirpath):
            continue
        for fn in filenames:
            stem, ext = os.path.splitext(fn)
            if ext not in ALL_EXTS:
                continue
            if (
                fn.startswith("test_")
                or fn.endswith(".test.ts")
                or fn.endswith(".spec.ts")
                or fn.endswith(".test.tsx")
                or fn.endswith(".spec.tsx")
                or fn.endswith("_test.go")
                or fn.endswith("_tests.rs")
                or fn in {"__init__.py", "types.py", "types.ts", "types.tsx", "types.go", "types.rs", "lib.rs", "mod.rs"}
                or stem in {"types"}
            ):
                continue
            impl_files.append(os.path.join(dirpath, fn))
    return sorted(impl_files)


def collect_test_files(root: str) -> list[str]:
    """Find test files across supported languages."""
    test_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if _should_skip_dir(dirpath):
            continue
        for fn in filenames:
            if (
                (fn.startswith("test_") and fn.endswith(".py"))
                or re.search(r"\.(test|spec)\.(ts|tsx|js|jsx)$", fn)
                or fn.endswith("_test.go")
                or fn.endswith("_tests.rs")
            ):
                test_files.append(os.path.join(dirpath, fn))
    return sorted(test_files)


def compute_docstring_coverage(func_metrics: list[dict]) -> float:
    if not func_metrics:
        return 0.0
    return sum(1 for f in func_metrics if f["has_docstring"]) / len(func_metrics)


def compute_type_depth(func_metrics: list[dict]) -> float:
    """Fraction of (params + return annotations) that are typed."""
    total = 0
    typed = 0
    for f in func_metrics:
        total += f["total_params"] + 1
        typed += f["typed_params"] + (1 if f["has_return_hint"] else 0)
    if total == 0:
        return 0.0
    return typed / total


def run_metrics(impl_dir: str) -> dict:
    """Run structural analysis and return metrics dict."""
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

    metrics = {
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
            "p95": round(sorted(body_lines)[min(len(body_lines) - 1, int(len(body_lines) * 0.95))], 1)
            if len(body_lines) > 1 else float(body_lines[0]),
        },
        "docstring_coverage": round(compute_docstring_coverage(all_funcs), 4),
        "type_annotation_depth": round(compute_type_depth(all_funcs), 4),
        "test_to_source_ratio": round(total_test_lines / total_impl_lines, 4) if total_impl_lines > 0 else 0.0,
        "try_except_total": total_try,
        "import_total": total_imports,
    }

    return metrics


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
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics written to {args.output}")
    else:
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
