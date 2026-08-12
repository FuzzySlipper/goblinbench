#!/usr/bin/env python3
"""Reject unfinished implementation residue in candidate-owned source."""

from __future__ import annotations

import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESIDUE = re.compile(r"\b(?:NotImplemented|TODO|FIXME)\b|\b(?:todo|unimplemented)!\s*\(")


def source_files() -> list[pathlib.Path]:
    sources = list((ROOT / "crates").glob("*/src/**/*.rs"))
    sources.extend((ROOT / "ts/packages").glob("*/src/**/*.ts"))
    return sorted(source for source in sources if "generated" not in source.parts)


def main() -> int:
    failures: list[str] = []
    for source in source_files():
        relative = source.relative_to(ROOT).as_posix()
        for line_number, line in enumerate(source.read_text().splitlines(), start=1):
            if match := RESIDUE.search(line):
                failures.append(
                    f"{relative}:{line_number} retains completion marker {match.group(0)!r}"
                )

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("completion hygiene: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
