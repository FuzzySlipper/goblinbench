"""Shared parsing helpers for first-class codebase-analysis scenarios."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_findings(text: str) -> list[dict[str, Any]] | None:
    """Extract a bounded ``findings`` array from direct or fenced JSON output."""
    candidates: list[str] = [text.strip()]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    )
    for candidate in candidates:
        parsed = _parse_findings_json(candidate)
        if parsed is not None:
            return parsed

    for start, char in enumerate(text):
        if char != "{":
            continue
        end = _balanced_object_end(text, start)
        if end is None:
            continue
        parsed = _parse_findings_json(text[start:end])
        if parsed is not None:
            return parsed
    return None


def _parse_findings_json(value: str) -> list[dict[str, Any]] | None:
    candidates = [value]
    quote_repaired = _repair_unescaped_quotes(value)
    if quote_repaired != value:
        candidates.append(quote_repaired)
    for candidate in candidates:
        parsed = _json_with_bounded_closer_repair(candidate)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
            continue
        findings = [item for item in parsed["findings"] if isinstance(item, dict)]
        return findings[:24]
    return None


def _json_with_bounded_closer_repair(value: str) -> Any | None:
    """Parse JSON, removing at most four provably blocking extra closers.

    The candidate edit is accepted only when it moves the parser's error
    strictly forward (or produces valid JSON), which keeps this recovery
    bounded and prevents arbitrary best-effort rewriting.
    """
    current = value
    for _attempt in range(5):
        try:
            return json.loads(current)
        except json.JSONDecodeError as error:
            if _attempt == 4:
                return None
            trials: list[tuple[int, str]] = []
            for position in (error.pos, error.pos - 1):
                if position < 0 or position >= len(current) or current[position] not in "}]":
                    continue
                trial = current[:position] + current[position + 1:]
                try:
                    return json.loads(trial)
                except json.JSONDecodeError as trial_error:
                    if trial_error.pos > error.pos:
                        trials.append((trial_error.pos, trial))
            if not trials:
                return None
            current = max(trials, key=lambda item: item[0])[1]
    return None


def _repair_unescaped_quotes(value: str) -> str:
    """Repair only quote characters that cannot terminate a JSON string.

    Architecture findings often quote source containing double-quoted string
    literals. Some models forget to escape those inner quotes even though the
    surrounding object is otherwise valid. In JSON a terminating quote must be
    followed (after whitespace) by a structural token. Quotes followed by
    source text are therefore unambiguously interior and can be escaped without
    guessing keys, values, or missing delimiters.
    """
    output: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(value):
        if not in_string:
            output.append(char)
            if char == '"':
                in_string = True
            continue
        if escaped:
            output.append(char)
            escaped = False
            continue
        if char == "\\":
            output.append(char)
            escaped = True
            continue
        if char != '"':
            output.append(char)
            continue
        next_index = index + 1
        while next_index < len(value) and value[next_index].isspace():
            next_index += 1
        next_char = value[next_index] if next_index < len(value) else ""
        if next_char in {"", ":", ",", "}", "]"}:
            output.append(char)
            in_string = False
        else:
            output.append('\\"')
    return "".join(output)


def _balanced_object_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, min(len(text), start + 100_000)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None
