#!/usr/bin/env python3
"""Run the hard native Rust/TypeScript GPT-5.6 comparison campaign.

Defaults to the two hard Rust systems fixtures plus the unguided TypeScript
backend fixture. Use ``--all-style-variants`` for the controlled TS prompt A/B/C.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CANDIDATES = REPO / "candidates.rusty-crew-native-gpt56-medium.json"
RUST_SCENARIOS = [
    "coding.leased-dag-queue-rust",
    "coding.framed-replica-rust",
]
TYPESCRIPT_BASELINE = ["coding.durable-workflow-engine-typescript"]
TYPESCRIPT_STYLE_VARIANTS = [
    "coding.durable-workflow-engine-typescript-style-guided",
    "coding.durable-workflow-engine-typescript-style-prose-guided",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Luna/Terra/Sol at medium effort on hard native coding fixtures"
    )
    parser.add_argument("--dry-run", action="store_true", help="print the exact gb-run command")
    parser.add_argument(
        "--language",
        action="append",
        choices=["rust", "typescript"],
        default=[],
        help="select one language (repeatable); default is both",
    )
    parser.add_argument(
        "--all-style-variants",
        action="store_true",
        help="include concise and prose TypeScript variants in addition to baseline",
    )
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="optionally select one or more candidate ids from the medium matrix",
    )
    args = parser.parse_args()

    languages = set(args.language or ["rust", "typescript"])
    scenarios: list[str] = []
    if "rust" in languages:
        scenarios.extend(RUST_SCENARIOS)
    if "typescript" in languages:
        scenarios.extend(TYPESCRIPT_BASELINE)
        if args.all_style_variants:
            scenarios.extend(TYPESCRIPT_STYLE_VARIANTS)

    if "typescript" not in languages:
        style_label = "no TypeScript cells"
    else:
        style_label = "all TS style variants" if args.all_style_variants else "TS baseline"
    command = [
        sys.executable,
        str(REPO / "scripts" / "gb-run.py"),
        "--candidates",
        str(CANDIDATES),
        "--label",
        f"GPT-5.6 native medium hard coding: {', '.join(sorted(languages))}; {style_label}",
    ]
    for scenario_id in scenarios:
        command.extend(["--scenario", scenario_id])
    for candidate_id in args.candidate:
        command.extend(["--candidate", candidate_id])

    print(shlex.join(command))
    if args.dry_run:
        return 0
    return subprocess.run(command, cwd=REPO, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
