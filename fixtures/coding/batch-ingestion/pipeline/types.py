"""Data types for the batch ingestion pipeline.

DO NOT MODIFY this file. It is the fixed interface for the probe.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Record:
    """A single data record flowing through the ingestion pipeline."""

    record_type: str
    ts: datetime
    payload: dict[str, Any]
    tags: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ValidationError:
    """Describes why a record failed validation."""

    field: str
    reason: str


@dataclass
class TypeSummary:
    """Aggregated summary for one record type."""

    record_type: str
    count: int
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    avg_payload_keys: float = 0.0


@dataclass
class BatchResult:
    """Final result of a batch ingestion run."""

    ingested: int = 0
    rejected: int = 0
    summaries: list[TypeSummary] = field(default_factory=list)
