"""Tests for batch-ingestion validation module."""

from datetime import datetime, timezone, timedelta

import pytest

from pipeline.types import Record, ValidationError
from pipeline.validate import validate_record, validate_batch


# ---------------------------------------------------------------------------
# validate_record
# ---------------------------------------------------------------------------

def test_valid_record_passes():
    """A fully valid record returns an empty error list."""
    r = Record(
        record_type="click",
        ts=datetime.now(timezone.utc),
        payload={"page": "/home"},
        tags={"mobile"},
    )
    errors = validate_record(r)
    assert errors == []


def test_empty_record_type_fails():
    r = Record(record_type="", ts=datetime.now(timezone.utc), payload={"a": 1})
    errors = validate_record(r)
    assert any(e.field == "record_type" for e in errors)


def test_non_alphanumeric_record_type_fails():
    r = Record(record_type="click/event!", ts=datetime.now(timezone.utc), payload={"a": 1})
    errors = validate_record(r)
    assert any(e.field == "record_type" for e in errors)


def test_future_timestamp_fails():
    r = Record(
        record_type="pageview",
        ts=datetime.now(timezone.utc) + timedelta(hours=2),
        payload={"url": "https://example.com"},
    )
    errors = validate_record(r)
    assert any(e.field == "ts" for e in errors)


def test_near_future_timestamp_allows_one_second_skew():
    """One second in the future is allowed (clock skew tolerance)."""
    r = Record(
        record_type="purchase",
        ts=datetime.now(timezone.utc) + timedelta(seconds=0.9),
        payload={"item": "book"},
    )
    errors = validate_record(r)
    ts_errors = [e for e in errors if e.field == "ts"]
    assert len(ts_errors) == 0


def test_empty_payload_fails():
    r = Record(record_type="search", ts=datetime.now(timezone.utc), payload={})
    errors = validate_record(r)
    assert any(e.field == "payload" for e in errors)


def test_multiple_errors_on_invalid_record():
    """A record with several violations returns all errors."""
    r = Record(
        record_type="",
        ts=datetime.now(timezone.utc) + timedelta(days=1),
        payload={},
    )
    errors = validate_record(r)
    assert len(errors) >= 3
    fields = {e.field for e in errors}
    assert "record_type" in fields
    assert "ts" in fields
    assert "payload" in fields


def test_input_not_mutated_by_validation():
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    r = Record(record_type="test", ts=ts, payload={"key": "val"}, tags={"a"})
    original = (r.record_type, r.ts, list(r.payload.keys()), list(r.tags))
    validate_record(r)
    assert (r.record_type, r.ts, list(r.payload.keys()), list(r.tags)) == original


# ---------------------------------------------------------------------------
# validate_batch
# ---------------------------------------------------------------------------

def test_batch_all_valid():
    ts = datetime.now(timezone.utc)
    records = [
        Record(record_type="a", ts=ts, payload={"x": 1}),
        Record(record_type="b", ts=ts, payload={"y": 2}),
    ]
    valid, invalid = validate_batch(records)
    assert len(valid) == 2
    assert len(invalid) == 0


def test_batch_some_invalid():
    ts = datetime.now(timezone.utc)
    records = [
        Record(record_type="valid", ts=ts, payload={"ok": True}),
        Record(record_type="", ts=ts, payload={"bad": "empty-type"}),
        Record(record_type="valid2", ts=ts, payload={"ok": False}),
    ]
    valid, invalid = validate_batch(records)
    assert len(valid) == 2
    assert len(invalid) == 1
    assert invalid[0][0].record_type == ""


def test_batch_preserves_order():
    ts = datetime.now(timezone.utc)
    records = [
        Record(record_type="x", ts=ts, payload={"n": 1}),
        Record(record_type="bad!", ts=ts, payload={"n": 2}),
        Record(record_type="y", ts=ts, payload={"n": 3}),
    ]
    valid, _ = validate_batch(records)
    assert [r.payload["n"] for r in valid] == [1, 3]


def test_batch_input_not_mutated():
    ts = datetime.now(timezone.utc)
    records = [
        Record(record_type="test", ts=ts, payload={"k": "v"}),
    ]
    validate_batch(records)
    assert records[0].record_type == "test"


@pytest.fixture
def many_valid() -> list[Record]:
    ts = datetime.now(timezone.utc)
    return [
        Record(record_type=f"type{i}", ts=ts, payload={"idx": i})
        for i in range(50)
    ]


def test_batch_large_input(many_valid):
    valid, invalid = validate_batch(many_valid)
    assert len(valid) == 50
    assert len(invalid) == 0
