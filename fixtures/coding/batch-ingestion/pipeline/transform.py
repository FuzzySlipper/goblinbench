"""Record transformation — sign your implementation here.

All function signatures are fixed. Fill the function bodies.
"""

from pipeline.types import Record


def normalize_payload(record: Record) -> Record:
    """Normalise payload keys to snake_case.

    For every key in payload:
      - Convert PascalCase/CamelCase keys to snake_case.
      - Trim whitespace from string values.
      - Leave non-string values unchanged.

    Return a new Record with the transformed payload.
    Do NOT mutate the input record.
    """
    ...


def flatten_payload(record: Record) -> Record:
    """Flatten one level of nested dict values in payload.

    e.g. {"user": {"name": "alice", "id": 7}} becomes
         {"user_name": "alice", "user_id": 7, ...other keys}

    Only flatten one level. Non-dict values stay as-is.
    Return a new Record with the flattened payload.
    """
    ...


def transform_batch(records: list[Record]) -> list[Record]:
    """Apply normalize_payload then flatten_payload to every record.

    Return new records in the original order.
    """
    ...
