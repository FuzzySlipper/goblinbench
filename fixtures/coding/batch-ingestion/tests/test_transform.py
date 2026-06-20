"""Tests for batch-ingestion transform module."""

from datetime import datetime, timezone

from pipeline.types import Record
from pipeline.transform import normalize_payload, flatten_payload, transform_batch


# ---------------------------------------------------------------------------
# normalize_payload
# ---------------------------------------------------------------------------

def test_snake_case_conversion():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"UserName": "alice", "LastLoginCount": 42},
    )
    result = normalize_payload(r)
    keys = list(result.payload.keys())
    assert "user_name" in keys
    assert "last_login_count" in keys
    assert "UserName" not in keys or "LastLoginCount" not in keys


def test_string_value_trimming():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"name": "  alice  ", "num": 42},
    )
    result = normalize_payload(r)
    assert result.payload["name"] == "alice"
    assert result.payload["num"] == 42


def test_input_not_mutated():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"OriginalKey": 1},
    )
    original_payload = dict(r.payload)
    normalize_payload(r)
    assert dict(r.payload) == original_payload


def test_empty_payload():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={},
    )
    result = normalize_payload(r)
    assert result.payload == {}


def test_already_snake_case_unchanged():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"already_snake": 1, "also_ok": "val"},
    )
    result = normalize_payload(r)
    assert "already_snake" in result.payload
    assert "also_ok" in result.payload


# ---------------------------------------------------------------------------
# flatten_payload
# ---------------------------------------------------------------------------

def test_flatten_one_level():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"user": {"name": "alice", "id": 7}, "page": "/home"},
    )
    result = flatten_payload(r)
    assert result.payload.get("user_name") == "alice"
    assert result.payload.get("user_id") == 7
    assert result.payload.get("page") == "/home"
    assert "user" not in result.payload


def test_non_dict_values_not_flattened():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"count": 5, "active": True},
    )
    result = flatten_payload(r)
    assert result.payload["count"] == 5
    assert result.payload["active"] is True


def test_flatten_only_one_level():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"nested": {"inner": {"deep": "value"}, "id": 1}},
    )
    result = flatten_payload(r)
    assert "nested_inner" in result.payload
    # inner should NOT be further flattened
    assert isinstance(result.payload["nested_inner"], dict)
    assert result.payload["nested_inner"]["deep"] == "value"


def test_flatten_input_not_mutated():
    r = Record(
        record_type="test",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        payload={"a": {"b": 1}, "c": 2},
    )
    original_payload = dict(r.payload)
    flatten_payload(r)
    assert dict(r.payload) == original_payload


# ---------------------------------------------------------------------------
# transform_batch
# ---------------------------------------------------------------------------

def test_transform_batch_pipeline():
    records = [
        Record(
            record_type="a",
            ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
            payload={"User": {"Name": "alice"}, "Score": 100},
        ),
        Record(
            record_type="b",
            ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
            payload={"Item": "book"},
        ),
    ]
    results = transform_batch(records)
    assert len(results) == 2
    # After normalize + flatten: "User" → "user", then flatten → "user_name"
    assert "user_name" in results[0].payload
    assert results[0].payload["score"] == 100


def test_transform_order_preserved():
    records = [
        Record(record_type="z", ts=datetime(2025, 1, 1, tzinfo=timezone.utc), payload={"A": 1}),
        Record(record_type="a", ts=datetime(2025, 1, 1, tzinfo=timezone.utc), payload={"B": 2}),
    ]
    results = transform_batch(records)
    assert [r.record_type for r in results] == ["z", "a"]


def test_transform_input_not_mutated():
    records = [
        Record(record_type="x", ts=datetime(2025, 1, 1, tzinfo=timezone.utc), payload={"Key": 1}),
    ]
    transform_batch(records)
    assert list(records[0].payload.keys()) == ["Key"]
