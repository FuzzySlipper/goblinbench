"""JSON serialization tuned to match the .NET runner's on-disk contract.

The C# harness serializes via ``System.Text.Json`` with these conventions:

  * property names come from ``[JsonPropertyName]`` attributes — all snake_case
    (``run_id``, ``candidate_results``, ``duration_ms``, ...). We mirror those
    names exactly via explicit ordering in each model's ``json_dict()``.
  * ``null`` is preserved (``error: null``, ``base_url: null``).
  * ``CandidateKind`` uses ``JsonStringEnumConverter`` and serializes to the
    PascalCase enum name (``"Unknown"``, ``OpenAiModel``, ``CodingAgent``).
  * ``DateTime`` is ISO-8601 round-trip with a trailing ``Z``.
  * output is ``WriteIndented`` (2-space).

We deliberately do **not** byte-match ``System.Text.Json``'s non-ASCII escaping
(it escapes everything non-ASCII to ``\\uXXXX``); we emit readable UTF-8 instead.
Any compliant JSON reader (including our own ``gb-results``/``gb-score``) parses
both identically, and that semantic equivalence is what the artifact diff checks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def now_iso() -> str:
    """Current UTC time as ISO-8601 with a trailing ``Z`` (mirrors .NET output)."""
    # .NET uses 7 fractional digits (ticks); Python datetime is microsecond (6).
    # Timestamps differ run-to-run anyway, so 6-digit precision is fine.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"


def to_serializable(obj: Any) -> Any:
    """Recursively convert a model graph into plain JSON-friendly Python.

    Handles: models exposing ``json_dict()``, ``datetime``, ``Enum``, and the
    standard containers (dict/list/tuple). Everything else passes through.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if hasattr(obj, "json_dict"):
        return to_serializable(obj.json_dict())
    if isinstance(obj, datetime):
        # .NET round-trip format; reuse now_iso's shape for consistency.
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_serializable(v) for v in obj]
    return obj


def dumps(obj: Any, indent: int = 2) -> str:
    """Serialize a model graph to a JSON string matching the .NET contract."""
    return json.dumps(to_serializable(obj), indent=indent, ensure_ascii=False)


@dataclass
class JsonLinesWriter:
    """Helper for trace.jsonl: one compact JSON object per line.

    Mirrors the .NET runner, which appends one ``JsonSerializer.Serialize(t)``
    (non-indented) per trace event, joined by newlines.
    """
    path: str

    def append(self, event: Any) -> None:
        line = json.dumps(to_serializable(event), ensure_ascii=False, separators=(",", ":"))
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
