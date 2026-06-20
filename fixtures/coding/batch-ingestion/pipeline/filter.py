"""Record filtering — sign your implementation here.

All function signatures are fixed. Fill the function bodies.
"""

from dataclasses import dataclass
from typing import Any

from pipeline.types import Record


@dataclass(frozen=True)
class FilterRule:
    """A single filter criterion."""

    field: str
    operator: str  # eq, neq, contains, gt, lt
    value: Any


def matches_filter_rule(record: Record, rule: FilterRule) -> bool:
    """Check whether a record satisfies a single filter rule.

    Supported operators:
      - eq / neq:   equality comparison on any field
      - contains:   value (str) in tags OR value (str) in
                    str(payload[key]) for payload fields
      - gt / lt:    numeric comparison on 'ts' only (as unix ts)

    'field' may be: "record_type", "ts", "payload:<key>", "tags"
    Return True if the rule is satisfied.
    """
    ...


def apply_filters(records: list[Record], rules: list[FilterRule]) -> list[Record]:
    """Return only records that satisfy ALL rules (AND logic).

    Preserve original order.
    Empty rules list → return all records unchanged.
    """
    ...
