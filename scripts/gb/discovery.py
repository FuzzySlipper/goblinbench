"""Scenario discovery — port of GoblinBench.Core.ScenarioDiscovery.

Loads scenarios from ``suites/`` following two conventions:

  Pattern 1: ``suites/<suite>/<scenario-id>.json``
  Pattern 2: ``suites/<suite>/<scenario-id>/scenario.json``

Auto-derives ``suite`` from the directory path (relative to ``suites/``) and
``id`` from the file/directory name when those fields aren't set in the JSON,
matching the C# behavior. Malformed files are skipped with a warning.
"""

from __future__ import annotations

import json
import os
from typing import Iterable

from .context import sanitize_file_name  # noqa: F401  (kept for import symmetry)
from .models import Scenario


def _load_scenario(path: str) -> Scenario | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as ex:
        # Match C#: log warning, skip malformed files (do not abort the run).
        import sys
        print(f"Warning: failed to load scenario '{path}': {ex}", file=sys.stderr)
        return None

    scenario = Scenario.from_dict(raw)

    # Auto-derive suite from directory path if not set.
    if not scenario.suite:
        parent = os.path.dirname(path)
        suites_idx = parent.lower().rfind("suites")
        if suites_idx >= 0:
            relative = parent[suites_idx + len("suites"):]
            relative = relative.lstrip(os.sep)
            scenario.suite = relative

    # Auto-derive id from filename if not set.
    if not scenario.id:
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem.lower() == "scenario":
            stem = os.path.basename(os.path.dirname(path)) or stem
        scenario.id = stem

    return scenario


def discover(suites_root: str) -> list[Scenario]:
    """Discover all scenarios under ``suites_root`` (both layout patterns)."""
    if not os.path.isdir(suites_root):
        return []

    scenarios: list[Scenario] = []
    loaded_ids: set[str] = set()

    # Pattern 1: any *.json directly under the suite tree (except scenario.json).
    for dirpath, _dirnames, filenames in os.walk(suites_root):
        for fname in filenames:
            if not fname.endswith(".json"):
                continue
            if fname.lower() == "scenario.json":
                continue  # handled by pattern 2
            scenario = _load_scenario(os.path.join(dirpath, fname))
            if scenario is not None:
                scenarios.append(scenario)
                if scenario.id:
                    loaded_ids.add(scenario.id.lower())

    # Pattern 2: <scenario-id>/scenario.json — skip if already loaded by pattern 1.
    for dirpath, _dirnames, filenames in os.walk(suites_root):
        if "scenario.json" not in filenames:
            continue
        dir_name = os.path.basename(dirpath)
        if dir_name.lower() in loaded_ids:
            continue
        scenario = _load_scenario(os.path.join(dirpath, "scenario.json"))
        if scenario is not None:
            scenarios.append(scenario)

    return scenarios


def filter_scenarios(
    scenarios: Iterable[Scenario],
    *,
    suite: str | None,
    scenario_id: str | None,
    skip: list[str] | None,
) -> list[Scenario]:
    """Apply the same --suite / --scenario / --skip-scenario filters as C#."""
    skip_lower = {s.lower() for s in (skip or [])}
    out: list[Scenario] = []
    for s in scenarios:
        if suite and s.suite.lower() != suite.lower():
            continue
        if scenario_id and s.id.lower() != scenario_id.lower():
            continue
        if skip_lower and s.id.lower() in skip_lower:
            continue
        out.append(s)
    return out
