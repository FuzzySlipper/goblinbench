from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys


REPO = pathlib.Path(__file__).resolve().parents[1]
SCORER_PATH = REPO / "scripts/scorers/asha-governance.py"
STARTER = REPO / "fixtures/coding/asha-authority-door"
REFERENCE = REPO / "tests/fixtures/asha-authority-door-reference"


def load_scorer():
    spec = importlib.util.spec_from_file_location("asha_governance_scorer", SCORER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def reference_workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    workspace = tmp_path / "fixture"
    shutil.copytree(
        STARTER,
        workspace,
        ignore=shutil.ignore_patterns("target", "node_modules", "__pycache__"),
    )
    shutil.copytree(REFERENCE, workspace, dirs_exist_ok=True)
    subprocess.run(
        ["cargo", "run", "-q", "-p", "protocol-codegen"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    return workspace


def test_reference_solution_passes_all_governance_gates(tmp_path: pathlib.Path) -> None:
    scorer = load_scorer()
    result = scorer.score_fixture(reference_workspace(tmp_path), threshold=0.8)

    assert result["passed"] is True
    assert result["score"] == 1.0
    assert result["detail"]["critical_failures"] == []
    assert all(gate["passed"] for gate in result["detail"]["gates"])


def test_starter_exposes_multiple_critical_failures(tmp_path: pathlib.Path) -> None:
    scorer = load_scorer()
    workspace = tmp_path / "fixture"
    shutil.copytree(
        STARTER,
        workspace,
        ignore=shutil.ignore_patterns("target", "node_modules", "__pycache__"),
    )

    result = scorer.score_fixture(workspace, threshold=0.8)

    assert result["passed"] is False
    assert result["score"] < 0.7
    assert {"authority-behavior", "replay-determinism", "generated-contracts"}.issubset(
        result["detail"]["critical_failures"]
    )


def test_protected_guidance_tampering_zeroes_score(tmp_path: pathlib.Path) -> None:
    scorer = load_scorer()
    workspace = reference_workspace(tmp_path)
    (workspace / "governance/boundary-rules.md").write_text("boundaries disabled\n")

    result = scorer.score_fixture(workspace, threshold=0.8)

    assert result["passed"] is False
    assert result["score"] == 0.0
    assert "protected file changed: governance/boundary-rules.md" in result["detail"][
        "protected_input_violations"
    ]


def test_completion_residue_has_a_small_separate_penalty(tmp_path: pathlib.Path) -> None:
    scorer = load_scorer()
    workspace = reference_workspace(tmp_path)
    rule = workspace / "crates/rule-door/src/lib.rs"
    rule.write_text(
        rule.read_text().replace(
            "    ApplyRejected(DoorApplyError),\n",
            "    ApplyRejected(DoorApplyError),\n    NotImplemented,\n",
        )
    )

    result = scorer.score_fixture(workspace, threshold=0.8)
    gates = {gate["id"]: gate for gate in result["detail"]["gates"]}

    assert result["score"] == 0.975
    assert gates["completion-hygiene"]["passed"] is False
    assert gates["guidance-reviewability"]["passed"] is True


def test_dense_source_and_completion_residue_are_scored_independently(
    tmp_path: pathlib.Path,
) -> None:
    scorer = load_scorer()
    workspace = reference_workspace(tmp_path)
    rule = workspace / "crates/rule-door/src/lib.rs"
    rule.write_text(
        rule.read_text().replace(
            "    ApplyRejected(DoorApplyError),\n",
            "    ApplyRejected(DoorApplyError),\n    NotImplemented,\n",
        )
    )
    renderer = workspace / "ts/packages/renderer-door/src/index.ts"
    renderer.write_text(
        renderer.read_text().replace(
            "  const openness = Math.max(0, Math.min(1000, projection.opennessMilli)) / 1000;\n"
            "  return {\n"
            "    entityId: projection.entityId,\n"
            "    openness,\n"
            "    stateLabel: projection.position,\n"
            "    revision: projection.revision,\n"
            "  };",
            "  return { entityId: projection.entityId, openness: Math.max(0, "
            "Math.min(1000, projection.opennessMilli)) / 1000, stateLabel: "
            "projection.position, revision: projection.revision };",
        )
    )

    result = scorer.score_fixture(workspace, threshold=0.8)
    gates = {gate["id"]: gate for gate in result["detail"]["gates"]}

    assert result["score"] == 0.96
    assert gates["completion-hygiene"]["passed"] is False
    assert gates["guidance-reviewability"]["passed"] is False


def test_scenario_declares_mixed_language_governance_scorer() -> None:
    scenario = json.loads((REPO / "suites/coding/asha-authority-door.json").read_text())

    assert scenario["input"]["fixture_case"] == "asha-authority-door"
    assert scenario["version"] == "1.1.0"
    assert scenario["scoring"]["scorers"][0] == "asha-governance"
    assert scenario["scoring"]["thresholds"]["asha-governance"] == 0.8
    assert {"rust", "typescript", "mixed-language", "generated-contracts"}.issubset(
        scenario["tags"]
    )
