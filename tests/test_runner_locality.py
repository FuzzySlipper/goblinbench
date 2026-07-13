from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from gb.models import CandidateConfig  # type: ignore[import-not-found]  # noqa: E402
from gb.runners.locality import CommandLocalityTracker  # type: ignore[import-not-found]  # noqa: E402


def test_locality_tracker_requires_literal_completed_pwd(tmp_path: Path) -> None:
    tracker = CommandLocalityTracker(str(tmp_path))
    tracker.observe({
        "id": "one", "command": "/bin/bash -lc pwd", "cwd": str(tmp_path),
        "output": str(tmp_path) + "\n", "status": "completed",
    }, "item/completed")

    assert tracker.passed is True
    assert tracker.evidence()["violations"] == []


def test_locality_tracker_rejects_declared_escape_and_chained_probe(tmp_path: Path) -> None:
    tracker = CommandLocalityTracker(str(tmp_path / "fixture"))
    tracker.observe({
        "id": "one", "command": "/bin/bash -lc 'pwd && rg --files'", "cwd": str(tmp_path),
        "output": str(tmp_path) + "\n", "status": "completed",
    }, "item/completed")

    evidence = tracker.evidence()
    assert tracker.passed is False
    assert "required standalone pwd probe was not observed" in evidence["violations"]
    assert any("outside fixture" in violation for violation in evidence["violations"])


def test_candidate_order_can_be_reversed() -> None:
    spec = importlib.util.spec_from_file_location("gb_run", SCRIPTS / "gb-run.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    candidates = [CandidateConfig(id="direct"), CandidateConfig(id="crew")]

    assert [value.id for value in module.order_candidates(candidates, "configured")] == ["direct", "crew"]
    assert [value.id for value in module.order_candidates(candidates, "reverse")] == ["crew", "direct"]
