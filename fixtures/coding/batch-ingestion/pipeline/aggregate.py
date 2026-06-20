"""Record aggregation — sign your implementation here.

All function signatures are fixed. Fill the function bodies.
"""

from pipeline.types import Record, TypeSummary


def group_by_type(records: list[Record]) -> dict[str, list[Record]]:
    """Group records by their 'record_type' field.

    Preserve insertion order within each group.
    """
    ...


def summarize_type(record_type: str, records: list[Record]) -> TypeSummary:
    """Compute aggregate stats for one group.

      - count = len(records)
      - first_ts / last_ts = min/max timestamps
      - avg_payload_keys = mean number of keys in payload

    If records is empty, return a summary with count=0.
    """
    ...


def aggregate_batch(records: list[Record]) -> list[TypeSummary]:
    """Group records by type and produce one TypeSummary per type.

    Types should appear in first-seen order. Return a flat list.
    """
    ...
