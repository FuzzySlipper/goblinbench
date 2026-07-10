from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_gb_score():  # type: ignore[no-untyped-def]
    path = REPO / "scripts" / "gb-score.py"
    spec = importlib.util.spec_from_file_location("goblinbench_gb_score", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_score_pipeline_resolves_legacy_id_without_suite_prefix() -> None:
    gb_score = _load_gb_score()

    scenario = gb_score.resolve_scenario("e2e-pi-mock")

    assert scenario is not None
    assert scenario["suite"] == "coding-smoke"
    assert scenario["scoring"]["scorers"] == ["coding-tests"]
