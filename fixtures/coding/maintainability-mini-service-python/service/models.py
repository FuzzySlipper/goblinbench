"""Fixed request/response and domain model types for the mini service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class User:
    id: str
    role: str = "viewer"
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    json: dict[str, Any] | None = None
    user: User | None = None


@dataclass(frozen=True)
class Response:
    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    email: str
    plan: str
    tags: tuple[str, ...] = field(default_factory=tuple)
