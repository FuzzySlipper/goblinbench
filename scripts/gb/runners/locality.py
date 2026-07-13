"""Shared workspace-locality evidence for coding-agent runners."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any


def task_with_locality_contract(task: str, fixture_dir: str) -> str:
    """Require a cheap, observable CWD preflight before benchmark work."""
    fixture = os.path.abspath(fixture_dir)
    return (
        "GoblinBench execution-isolation contract:\n"
        "Before any other shell or tool command, run exactly `pwd` as a standalone "
        "command (do not chain it with another command). Its output must be exactly:\n"
        f"{fixture}\n"
        "If it differs, stop without inspecting or changing any files. Keep all file "
        "inspection and changes inside that fixture directory.\n\n"
        f"{task}"
    )


class CommandLocalityTracker:
    """Validate command CWD metadata and the required literal ``pwd`` probe."""

    def __init__(self, fixture_dir: str) -> None:
        self.fixture_dir = os.path.abspath(fixture_dir)
        self.command_ids: set[str] = set()
        self.declared_cwds: set[str] = set()
        self.probe_command: str | None = None
        self.observed_cwd: str | None = None
        self.violations: list[str] = []

    def observe(self, item: dict[str, Any], native_method: str = "") -> None:
        item_id = item.get("id") or item.get("itemId")
        if isinstance(item_id, str) and item_id:
            self.command_ids.add(item_id)

        cwd = item.get("cwd")
        if isinstance(cwd, str) and cwd:
            declared = os.path.abspath(cwd)
            self.declared_cwds.add(declared)
            if not _is_within(declared, self.fixture_dir):
                self._violate(f"command declared cwd outside fixture: {declared}")

        command = item.get("command")
        if not isinstance(command, str) or not _is_standalone_pwd(command):
            return
        self.probe_command = command
        if native_method not in {"item/completed", "completed"} and item.get("status") != "completed":
            return
        output = item.get("output") or item.get("aggregatedOutput")
        if not isinstance(output, str):
            self._violate("standalone pwd probe completed without textual output")
            return
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        self.observed_cwd = os.path.abspath(lines[0]) if lines else ""
        if self.observed_cwd != self.fixture_dir:
            self._violate(
                f"standalone pwd probe resolved outside fixture: {self.observed_cwd or '<empty>'}"
            )

    @property
    def passed(self) -> bool:
        return bool(self.probe_command and self.observed_cwd == self.fixture_dir and not self.violations)

    def evidence(self) -> dict[str, Any]:
        violations = list(self.violations)
        if not self.probe_command:
            violations.append("required standalone pwd probe was not observed")
        elif self.observed_cwd is None:
            violations.append("standalone pwd probe did not complete")
        return {
            "required_fixture_dir": self.fixture_dir,
            "probe_command": self.probe_command,
            "observed_cwd": self.observed_cwd,
            "declared_command_cwds": sorted(self.declared_cwds),
            "command_count": len(self.command_ids),
            "violations": violations,
            "passed": self.passed,
        }

    def _violate(self, message: str) -> None:
        if message not in self.violations:
            self.violations.append(message)


def _is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([Path(path).resolve(), Path(root).resolve()]) == str(Path(root).resolve())
    except ValueError:
        return False


def _is_standalone_pwd(command: str) -> bool:
    """Recognize native command wrappers around an otherwise literal ``pwd``."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) == 1:
        return os.path.basename(tokens[0]) == "pwd"
    if len(tokens) == 3 and os.path.basename(tokens[0]) in {"bash", "sh", "zsh"} and tokens[1] in {"-c", "-lc"}:
        try:
            inner = shlex.split(tokens[2])
        except ValueError:
            return False
        return len(inner) == 1 and os.path.basename(inner[0]) == "pwd"
    return False
