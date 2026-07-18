#!/usr/bin/env python3
"""Vocabulary blocker plus advisory source-shape pressure report."""

from __future__ import annotations

import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
BANNED_TYPE = re.compile(
    r"\b(?:struct|enum|class|interface|type)\s+[A-Za-z0-9_]*(?:Component|Archetype|WorldState|System)\b"
)
BANNED_EXPLICIT_ANY = re.compile(r"(?::|\bas)\s*any\b|<any>")
BANNED_POLICY_RUNTIME = re.compile(
    r"\b(?:Date\.now|performance\.now|Math\.random|setTimeout|setInterval)\b"
)
BANNED_AUTHORITY_RUNTIME = re.compile(
    r"\b(?:SystemTime|Instant::now|thread_rng|random::<|rand::)"
)


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    sources = sorted((ROOT / "crates").glob("*/src/*.rs")) + sorted(
        (ROOT / "ts/packages").glob("*/src/*.ts")
    )
    for source in sources:
        relative = source.relative_to(ROOT).as_posix()
        text = source.read_text()
        if BANNED_TYPE.search(text):
            failures.append(f"{relative} introduces forbidden ECS/plugin-gravity vocabulary")
        if source.suffix == ".ts" and BANNED_EXPLICIT_ANY.search(text):
            failures.append(f"{relative} uses explicit any")
        if "ts/packages/policy-" in relative and BANNED_POLICY_RUNTIME.search(text):
            failures.append(f"{relative} reads nondeterministic runtime state from policy")
        if relative.startswith(("crates/core-state/", "crates/rule-", "crates/sim-")) and BANNED_AUTHORITY_RUNTIME.search(text):
            failures.append(f"{relative} reads nondeterministic runtime state from authority")
        lines = len(text.splitlines())
        if lines > 220:
            warnings.append(f"{relative} has {lines} lines; review ownership pressure")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"guidance checks: OK ({len(warnings)} advisory warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
