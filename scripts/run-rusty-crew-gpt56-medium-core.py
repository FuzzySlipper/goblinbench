#!/usr/bin/env python3
"""Run the intentional-medium native GPT-5.6 core campaign.

The campaign deliberately excludes fake-MCP suites until they have a native
Rusty Crew adapter. Every selected cell is stored by the normal gb-run path.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CANDIDATES = REPO / "candidates.rusty-crew-native-gpt56-medium.json"
SCENARIOS = [
    "autonomy-calibration.clear-smoke-test-after-patch",
    "autonomy-calibration.mcp-tool-limitation-bypass-script",
    "autonomy-calibration.two-source-repo-conflict",
    "evidence-grounding.model-capability-incomplete-logs",
    "evidence-grounding.partial-thread-status-brief",
    "evidence-grounding.self-report-vs-review-packet",
    "coding.maintainability-mini-service-go",
    "coding.maintainability-mini-service-typescript",
    "coding.maintainability-mini-service-rust",
    "codebase-analysis.den-core-v1",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Luna/Terra/Sol at explicit medium effort on the native core campaign"
    )
    parser.add_argument("--dry-run", action="store_true", help="print the exact gb-run command")
    parser.add_argument(
        "--candidate", action="append", default=[],
        help="optionally select one or more candidate ids from the medium matrix",
    )
    args = parser.parse_args()

    command = [
        sys.executable,
        str(REPO / "scripts" / "gb-run.py"),
        "--candidates",
        str(CANDIDATES),
        "--label",
        "GPT-5.6 native medium core: autonomy, grounding, maintainability, architecture",
    ]
    for scenario_id in SCENARIOS:
        command.extend(["--scenario", scenario_id])
    for candidate_id in args.candidate:
        command.extend(["--candidate", candidate_id])

    print(shlex.join(command))
    if args.dry_run:
        return 0
    return subprocess.run(command, cwd=REPO, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
