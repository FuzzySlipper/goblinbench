from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys


REPO = Path(__file__).resolve().parents[1]
SCORER = REPO / "scripts" / "scorers" / "architecture-quality.py"
spec = importlib.util.spec_from_file_location("architecture_quality_scorer", SCORER)
assert spec is not None and spec.loader is not None
scorer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scorer
spec.loader.exec_module(scorer)


TS_PARAMS = {
    "source_root": "src",
    "baseline_path": ".goblinbench/maintainability-baseline.json",
    "gold_path": ".goblinbench/architecture.md",
    "central_paths": ["src/engine.ts", "src/repository.ts"],
    "setup_paths": ["src/engine.ts"],
    "handler_paths": ["src/engine.ts"],
    "dependency_rules": [
        {"from": "src/validation.ts", "forbid": ["engine", "repository", "outbox"]},
    ],
    "gates": {
        "min_changed_files": 4,
        "max_central_changed_mass_share": 0.72,
        "max_handler_function_lines": 90,
        "max_cross_file_duplication_ratio": 0.1,
    },
}


def test_architecture_quality_baseline_is_clean() -> None:
    fixture = REPO / "fixtures" / "coding" / "durable-workflow-engine-ts"
    result = scorer.score_architecture(fixture, TS_PARAMS, 0.65)

    assert result["success"] is True
    assert result["score"] == 1.0
    assert result["detail"]["gold_expectations_present"] is True
    assert result["detail"]["dependency_violations"] == []


def test_architecture_quality_reports_direction_and_seam_penalties(tmp_path: Path) -> None:
    source = REPO / "fixtures" / "coding" / "durable-workflow-engine-ts"
    fixture = tmp_path / "fixture"
    shutil.copytree(source, fixture)
    validation = fixture / "src" / "validation.ts"
    validation.write_text(
        'import { WorkflowEngine } from "./engine";\n' + validation.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = scorer.score_architecture(fixture, TS_PARAMS, 0.65)

    assert result["score"] < 1.0
    assert result["detail"]["dependency_violations"] == [
        {"file": "src/validation.ts", "import": "./engine", "forbidden": "engine"}
    ]
    assert {item["gate"] for item in result["detail"]["penalties"]} == {
        "dependency-direction",
        "seam-preservation",
    }


def test_hard_scenarios_keep_behavior_and_architecture_scores_separate() -> None:
    scenario_paths = [
        REPO / "suites" / "coding" / "leased-dag-queue-rust.json",
        REPO / "suites" / "coding" / "framed-replica-rust.json",
        REPO / "suites" / "coding" / "durable-workflow-engine-typescript.json",
        REPO / "suites" / "coding" / "durable-workflow-engine-typescript-style-guided.json",
        REPO / "suites" / "coding" / "durable-workflow-engine-typescript-style-prose-guided.json",
    ]

    for path in scenario_paths:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        assert "coding-tests" in scenario["scoring"]["scorers"]
        assert "architecture-quality" in scenario["scoring"]["scorers"]
        assert scenario["scoring"]["thresholds"]["coding-tests"] == 1.0
        assert scenario["scoring"]["thresholds"]["architecture-quality"] == 0.65
