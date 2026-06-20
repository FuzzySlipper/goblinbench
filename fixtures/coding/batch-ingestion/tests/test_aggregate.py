"""Tests for batch-ingestion aggregation module."""

from datetime import datetime, timezone

from pipeline.types import Record, TypeSummary
from pipeline.aggregate import group_by_type, summarize_type, aggregate_batch


def _r(record_type: str, payload: dict | None = None) -> Record:
    return Record(
        record_type=record_type,
        ts=datetime(2025, 6, 1, tzinfo=timezone.utc),
        payload=payload or {"k": 1},
    )


# ---------------------------------------------------------------------------
# group_by_type
# ---------------------------------------------------------------------------


def test_group_by_single_type():
    records = [_r("click"), _r("click")]
    groups = group_by_type(records)
    assert set(groups.keys()) == {"click"}
    assert len(groups["click"]) == 2


def test_group_by_multiple_types():
    records = [_r("click"), _r("pageview"), _r("click")]
    groups = group_by_type(records)
    assert set(groups.keys()) == {"click", "pageview"}
    assert len(groups["click"]) == 2
    assert len(groups["pageview"]) == 1


def test_group_preserves_order_within_group():
    ts1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2025, 6, 1, tzinfo=timezone.utc)
    records = [
        Record(record_type="a", ts=ts1, payload={"n": 1}),
        Record(record_type="a", ts=ts2, payload={"n": 2}),
    ]
    groups = group_by_type(records)
    assert [r.payload["n"] for r in groups["a"]] == [1, 2]


# ---------------------------------------------------------------------------
# summarize_type
# ---------------------------------------------------------------------------


def test_summarize_single_record():
    ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    records = [Record(record_type="click", ts=ts, payload={"a": 1, "b": 2})]
    s = summarize_type("click", records)
    assert s.record_type == "click"
    assert s.count == 1
    assert s.first_ts == ts
    assert s.last_ts == ts
    assert s.avg_payload_keys == 2.0


def test_summarize_multiple():
    records = [
        Record(record_type="click", ts=datetime(2025, 1, 1, tzinfo=timezone.utc), payload={"a": 1}),
        Record(record_type="click", ts=datetime(2025, 6, 1, tzinfo=timezone.utc), payload={"a": 1, "b": 2}),
    ]
    s = summarize_type("click", records)
    assert s.count == 2
    assert s.first_ts == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert s.last_ts == datetime(2025, 6, 1, tzinfo=timezone.utc)
    assert s.avg_payload_keys == 1.5


def test_summarize_empty():
    s = summarize_type("empty_type", [])
    assert s.record_type == "empty_type"
    assert s.count == 0
    assert s.avg_payload_keys == 0.0


# ---------------------------------------------------------------------------
# aggregate_batch
# ---------------------------------------------------------------------------


def test_aggregate_batch():
    records = [
        _r("click"),
        _r("pageview"),
        _r("click"),
    ]
    summaries = aggregate_batch(records)
    type_map = {s.record_type: s for s in summaries}
    assert "click" in type_map
    assert "pageview" in type_map
    assert type_map["click"].count == 2
    assert type_map["pageview"].count == 1


def test_aggregate_first_seen_order():
    records = [
        _r("b"),
        _r("a"),
        _r("c"),
    ]
    summaries = aggregate_batch(records)
    assert [s.record_type for s in summaries] == ["b", "a", "c"]


def test_aggregate_empty():
    assert aggregate_batch([]) == []
