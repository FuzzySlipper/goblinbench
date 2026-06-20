"""Tests for batch-ingestion filter module."""

from datetime import datetime, timezone

from pipeline.types import Record
from pipeline.filter import FilterRule, matches_filter_rule, apply_filters


def _r(**overrides) -> Record:
    """Helper to build a test record with defaults."""
    defaults = {
        "record_type": "click",
        "ts": datetime(2025, 6, 1, tzinfo=timezone.utc),
        "payload": {"url": "/home", "count": 5},
        "tags": {"mobile", "us-east"},
    }
    defaults.update(overrides)
    return Record(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# matches_filter_rule
# ---------------------------------------------------------------------------


def test_eq_match():
    rule = FilterRule(field="record_type", operator="eq", value="click")
    assert matches_filter_rule(_r(), rule)


def test_eq_no_match():
    rule = FilterRule(field="record_type", operator="eq", value="pageview")
    assert not matches_filter_rule(_r(), rule)


def test_neq_match():
    rule = FilterRule(field="record_type", operator="neq", value="pageview")
    assert matches_filter_rule(_r(), rule)


def test_contains_tag():
    rule = FilterRule(field="tags", operator="contains", value="mobile")
    assert matches_filter_rule(_r(), rule)


def test_not_contains_tag():
    rule = FilterRule(field="tags", operator="contains", value="europe")
    assert not matches_filter_rule(_r(), rule)


def test_gt_timestamp():
    later = datetime(2025, 7, 1, tzinfo=timezone.utc)
    rule = FilterRule(field="ts", operator="gt", value="2025-06-15T00:00:00+00:00")
    assert matches_filter_rule(_r(ts=later), rule)


def test_lt_timestamp():
    earlier = datetime(2025, 5, 1, tzinfo=timezone.utc)
    rule = FilterRule(field="ts", operator="lt", value="2025-06-15T00:00:00+00:00")
    assert matches_filter_rule(_r(ts=earlier), rule)


def test_payload_field_eq():
    rule = FilterRule(field="payload:url", operator="eq", value="/home")
    assert matches_filter_rule(_r(), rule)


def test_payload_field_contains():
    rule = FilterRule(field="payload:url", operator="contains", value="home")
    assert matches_filter_rule(_r(), rule)


def test_unknown_field_returns_false():
    rule = FilterRule(field="nonexistent", operator="eq", value="x")
    assert not matches_filter_rule(_r(), rule)


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------


def test_no_rules_returns_all():
    records = [_r(record_type="a"), _r(record_type="b")]
    result = apply_filters(records, [])
    assert len(result) == 2


def test_single_rule():
    records = [
        _r(record_type="click"),
        _r(record_type="pageview"),
        _r(record_type="click"),
    ]
    rules = [FilterRule(field="record_type", operator="eq", value="click")]
    result = apply_filters(records, rules)
    assert len(result) == 2
    assert all(r.record_type == "click" for r in result)


def test_multiple_rules_and():
    records = [
        _r(record_type="click", tags={"mobile"}),
        _r(record_type="click", tags={"desktop"}),
        _r(record_type="pageview", tags={"mobile"}),
    ]
    rules = [
        FilterRule(field="record_type", operator="eq", value="click"),
        FilterRule(field="tags", operator="contains", value="mobile"),
    ]
    result = apply_filters(records, rules)
    # Only 'click' + 'mobile' matches both
    assert len(result) == 1
    assert result[0].record_type == "click"
    assert "mobile" in result[0].tags


def test_order_preserved():
    records = [
        _r(record_type="c"),
        _r(record_type="a"),
        _r(record_type="b"),
    ]
    rules = [FilterRule(field="record_type", operator="neq", value="x")]
    result = apply_filters(records, rules)
    assert [r.record_type for r in result] == ["c", "a", "b"]


def test_no_match_yields_empty():
    records = [_r(record_type="click")]
    rules = [FilterRule(field="record_type", operator="eq", value="nonexistent")]
    result = apply_filters(records, rules)
    assert result == []
