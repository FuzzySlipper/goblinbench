#!/usr/bin/env python3
"""Import the original agent-lab coding cases into GoblinBench fixtures.

Usage:
    scripts/import-agent-lab-cases.py --agent-lab /tmp/agent-lab-inspect
    scripts/import-agent-lab-cases.py --agent-lab /path/to/agent-lab --case cache-key --overwrite

The importer preserves the upstream EvalLab.Core/EvalLab.Tests path shape so the
original task prompt target files remain meaningful inside the fixture workspace.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


CASES: dict[str, dict[str, str | bool]] = {
    "cache-key": {
        "name": "Cache Key Stability",
        "core_dir": "CacheKeys",
        "visible": "FilterCacheKeyVisibleTests.cs",
        "strict": "FilterCacheKeyStrictTests.cs",
        "project": "CacheKeyTests.csproj",
    },
    "export-report": {
        "name": "Export Report Generator",
        "core_dir": "ExportReport",
        "visible": "ExportReportVisibleTests.cs",
        "strict": "ExportReportStrictTests.cs",
        "project": "ExportReportTests.csproj",
    },
    "expression-evaluator": {
        "name": "Expression Evaluator",
        "core_dir": "ExpressionEvaluator",
        "visible": "ExpressionEvaluatorVisibleTests.cs",
        "strict": "ExpressionEvaluatorStrictTests.cs",
        "project": "ExpressionEvaluatorTests.csproj",
    },
    "kth-selection": {
        "name": "K-th Selection",
        "core_dir": "KthSelection",
        "visible": "KthSelectionVisibleTests.cs",
        "strict": "KthSelectionStrictTests.cs",
        "project": "KthSelectionTests.csproj",
    },
    "roman-numerals": {
        "name": "Roman Numerals",
        "core_dir": "RomanNumerals",
        "visible": "RomanNumeralsVisibleTests.cs",
        "strict": "RomanNumeralsStrictTests.cs",
        "project": "RomanNumeralsTests.csproj",
    },
    "tree-prune": {
        "name": "Tree Prune",
        "core_dir": "TreePrune",
        "visible": "TreePruneVisibleTests.cs",
        "strict": "TreePruneStrictTests.cs",
        "project": "TreePruneTests.csproj",
        "tree_support": True,
    },
    "weighted-split": {
        "name": "Weighted Split Calculator",
        "core_dir": "WeightedSplit",
        "visible": "WeightedSplitVisibleTests.cs",
        "strict": "WeightedSplitStrictTests.cs",
        "project": "WeightedSplitTests.csproj",
    },
}

CSPROJ_TEMPLATE = """<Project Sdk=\"Microsoft.NET.Sdk\">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <IsPackable>false</IsPackable>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include=\"EvalLab.Core/**/*.cs\" />
    <Compile Include=\"EvalLab.Tests/**/*.cs\" />
  </ItemGroup>
  <ItemGroup>
    <PackageReference Include=\"Microsoft.NET.Test.Sdk\" Version=\"17.14.1\" />
    <PackageReference Include=\"xunit\" Version=\"2.9.3\" />
    <PackageReference Include=\"xunit.runner.visualstudio\" Version=\"3.1.4\" />
    <Using Include=\"Xunit\" />
  </ItemGroup>
</Project>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-lab", required=True, type=Path, help="Path to a clone of FuzzySlipper/agent-lab")
    parser.add_argument("--repo", default=Path(__file__).resolve().parents[1], type=Path, help="GoblinBench repo root")
    parser.add_argument("--case", choices=sorted(CASES), action="append", dest="cases", help="Case slug to import; repeatable. Defaults to all cases.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing fixture/scenario outputs")
    return parser.parse_args()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)


def require_dir(path: Path) -> None:
    if not path.is_dir():
        raise FileNotFoundError(path)


def copy2(src: Path, dest: Path) -> None:
    require_file(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def import_case(repo: Path, agent_lab: Path, slug: str, overwrite: bool) -> dict[str, str]:
    cfg = CASES[slug]
    fixture = repo / "fixtures" / "coding" / slug
    scenario_path = repo / "suites" / "coding" / f"{slug}.json"

    if fixture.exists():
        if not overwrite:
            raise FileExistsError(f"fixture already exists: {fixture}")
        shutil.rmtree(fixture)
    if scenario_path.exists() and not overwrite:
        raise FileExistsError(f"scenario already exists: {scenario_path}")

    core_dir = str(cfg["core_dir"])
    require_dir(agent_lab / "EvalLab.Core" / "Cases" / core_dir)
    require_file(agent_lab / "EvalCases" / f"{slug}.md")

    shutil.copytree(
        agent_lab / "EvalLab.Core" / "Cases" / core_dir,
        fixture / "EvalLab.Core" / "Cases" / core_dir,
    )
    copy2(agent_lab / "EvalLab.Tests" / "Visible" / str(cfg["visible"]), fixture / "EvalLab.Tests" / "Visible" / str(cfg["visible"]))
    copy2(agent_lab / "EvalLab.Tests" / "Strict" / str(cfg["strict"]), fixture / "EvalLab.Tests" / "Strict" / str(cfg["strict"]))

    support_dir = fixture / "EvalLab.Tests" / "Support"
    copy2(agent_lab / "EvalLab.Tests" / "Support" / "PlaceholderScanPatterns.cs", support_dir / "PlaceholderScanPatterns.cs")
    if cfg.get("tree_support"):
        copy2(agent_lab / "EvalLab.Tests" / "Support" / "TreeSerialize.cs", support_dir / "TreeSerialize.cs")

    (fixture / str(cfg["project"])).write_text(CSPROJ_TEMPLATE, encoding="utf-8")

    task = (agent_lab / "EvalCases" / f"{slug}.md").read_text(encoding="utf-8").strip()
    scenario = {
        "id": f"coding.{slug}",
        "version": "1.0.0",
        "name": f"{cfg['name']} — agent-lab port",
        "description": "Original agent-lab coding maintenance task ported into the GoblinBench coding-agent harness.",
        "suite": "coding",
        "input": {
            "task": task,
            "fixture_case": slug,
            "agent_lab_source": f"https://github.com/FuzzySlipper/agent-lab/blob/main/EvalCases/{slug}.md",
            "agent_lab_fixture_source": f"https://github.com/FuzzySlipper/agent-lab/tree/main/EvalLab.Core/Cases/{core_dir}",
        },
        "scoring": {
            "scorers": ["coding-tests", "latency"],
            "parameters": {
                "coding-tests": {
                    "test_project": str(cfg["project"]),
                    "visible_filter": "FullyQualifiedName~EvalLab.Tests.Visible",
                    "strict_filter": "FullyQualifiedName~EvalLab.Tests.Strict",
                    "scan_dir": f"EvalLab.Core/Cases/{core_dir}",
                    "timeout_seconds": 120,
                }
            },
            # Old agent-lab coding tasks should only pass when visible + strict + marker scan are clean.
            "thresholds": {"coding-tests": 1.0},
        },
        "timeout_seconds": 300,
    }
    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    return {"case": slug, "fixture": str(fixture), "scenario": str(scenario_path)}


def main() -> None:
    args = parse_args()
    repo = args.repo.resolve()
    agent_lab = args.agent_lab.resolve()
    require_dir(repo / "fixtures" / "coding")
    require_dir(repo / "suites" / "coding")
    require_dir(agent_lab / "EvalLab.Core" / "Cases")
    require_dir(agent_lab / "EvalLab.Tests")
    selected = args.cases or sorted(CASES)
    results = [import_case(repo, agent_lab, slug, args.overwrite) for slug in selected]
    print(json.dumps({"imported": results}, indent=2))


if __name__ == "__main__":
    main()
