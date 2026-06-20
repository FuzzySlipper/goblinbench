"""Audit event sink for the mini service."""

from __future__ import annotations

from typing import Any


class AuditLog:
    """Tiny in-memory audit log used by tests and metrics fixtures."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record(self, event_type: str, actor_id: str, payload: dict[str, Any]) -> None:
        self._events.append({"type": event_type, "actor_id": actor_id, "payload": dict(payload)})

    def list_events(self) -> list[dict[str, Any]]:
        return list(self._events)
