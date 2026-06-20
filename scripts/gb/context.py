"""RunContext — artifact path helpers (port of GoblinBench.Core.RunContext).

Mirrors the C# path resolution exactly, including scenario-scoped layout:
``runs/<run-id>/scenarios/<scenario-id>/candidates/<candidate-id>/`` when a
scenario id is set, or ``runs/<run-id>/candidates/<candidate-id>/`` otherwise.
The main loop always sets a scenario id (see gb-run.py), so the scenarios/
layout is what every real run produces.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def sanitize_file_name(name: str) -> str:
    """Port of C# ``Path.GetInvalidFileNameChars()`` replacement.

    On Unix, .NET's invalid-file-name chars are ``/`` and ``\\0``; on Windows a
    larger set applies. We sanitize the Unix-relevant set plus backslash for
    cross-platform safety. Falls back to ``'candidate'`` if empty (matches C#).
    """
    invalid = {"/", "\\", "\0"}
    sanitized = "".join("_" if c in invalid else c for c in (name or ""))
    return sanitized if sanitized.strip() else "candidate"


@dataclass
class RunContext:
    run_id: str = ""
    started_at: str = ""
    run_directory: str = ""
    runs_root: str = ""
    repo_root: str | None = None
    scenario_id: str | None = None
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def candidate_directory(self, candidate_id: str) -> str:
        base = self.run_directory
        if self.scenario_id:
            base = os.path.join(base, "scenarios", sanitize_file_name(self.scenario_id))
        return os.path.join(base, "candidates", sanitize_file_name(candidate_id))

    def candidate_output_path(self, candidate_id: str) -> str:
        return os.path.join(self.candidate_directory(candidate_id), "output.json")

    def candidate_trace_path(self, candidate_id: str) -> str:
        return os.path.join(self.candidate_directory(candidate_id), "trace.jsonl")

    def candidate_scores_path(self, candidate_id: str) -> str:
        return os.path.join(self.candidate_directory(candidate_id), "scores.json")

    def candidate_artifacts_directory(self, candidate_id: str) -> str:
        return os.path.join(self.candidate_directory(candidate_id), "artifacts")
