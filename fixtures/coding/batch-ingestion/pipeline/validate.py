"""Record validation — sign your implementation here.

All function signatures are fixed. Fill the function bodies.
"""

from pipeline.types import Record, ValidationError


def validate_record(record: Record) -> list[ValidationError]:
    """Check a single record against all validation rules.

    Rules:
      - 'record_type' must be non-empty and alphanumeric.
      - 'ts' must not be in the future (allow 1 s clock skew).
      - 'payload' must be non-empty.
      - 'tags' may be empty (no rule required).

    Return a list of errors (empty = valid).
    """
    ...


def validate_batch(
    records: list[Record],
) -> tuple[list[Record], list[tuple[Record, list[ValidationError]]]]:
    """Split records into (valid, invalid_with_errors).

    Invalid records are paired with their validation errors.
    Order of valid records must match input order.
    """
    ...
