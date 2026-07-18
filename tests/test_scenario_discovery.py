from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from gb.discovery import discover, filter_scenarios  # type: ignore[import-not-found]  # noqa: E402
from gb.models import Scenario  # type: ignore[import-not-found]  # noqa: E402


def test_filter_scenarios_accepts_multiple_exact_ids() -> None:
    scenarios = [
        Scenario(id="coding.go", suite="coding"),
        Scenario(id="coding.rust", suite="coding"),
        Scenario(id="vision.ui", suite="vision"),
    ]

    selected = filter_scenarios(
        scenarios,
        suite=None,
        scenario_ids=["coding.go", "vision.ui"],
        skip=None,
    )

    assert [scenario.id for scenario in selected] == ["coding.go", "vision.ui"]


def test_filter_scenarios_combines_suite_and_exact_ids_as_intersection() -> None:
    scenarios = [
        Scenario(id="coding.go", suite="coding"),
        Scenario(id="vision.ui", suite="vision"),
    ]

    selected = filter_scenarios(
        scenarios,
        suite="coding",
        scenario_ids=["coding.go", "vision.ui"],
        skip=None,
    )

    assert [scenario.id for scenario in selected] == ["coding.go"]


def test_filter_scenarios_requires_all_requested_tags() -> None:
    scenarios = [
        Scenario(id="coding.rust-hard", suite="coding", tags=["rust", "hard"]),
        Scenario(id="coding.rust-small", suite="coding", tags=["rust"]),
        Scenario(id="coding.ts-hard", suite="coding", tags=["typescript", "hard"]),
    ]

    selected = filter_scenarios(
        scenarios,
        suite="coding",
        tags=["rust", "hard"],
    )

    assert [scenario.id for scenario in selected] == ["coding.rust-hard"]


def test_hard_coding_scenarios_discover_with_shared_typescript_fixture() -> None:
    scenarios = {scenario.id: scenario for scenario in discover(str(REPO / "suites"))}
    expected = {
        "coding.leased-dag-queue-rust": "leased-dag-queue-rust",
        "coding.framed-replica-rust": "framed-replica-rust",
        "coding.durable-workflow-engine-typescript": "durable-workflow-engine-ts",
        "coding.durable-workflow-engine-typescript-style-guided": "durable-workflow-engine-ts",
        "coding.durable-workflow-engine-typescript-style-prose-guided": "durable-workflow-engine-ts",
        "coding.asha-authority-door": "asha-authority-door",
    }

    for scenario_id, fixture_case in expected.items():
        scenario = scenarios[scenario_id]
        assert scenario.suite == "coding"
        assert scenario.input["fixture_case"] == fixture_case
        assert "hard" in scenario.tags
        assert (REPO / "fixtures" / "coding" / fixture_case).is_dir()
