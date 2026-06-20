package pipeline

import (
	"testing"
	"time"
)

func filterRecord(overrides ...func(*Record)) Record {
	r := Record{
		RecordType: "click",
		TS:         time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC),
		Payload:    Payload{"url": "/home", "count": 5},
		Tags:       StringSet{"mobile": {}, "us-east": {}},
	}
	for _, f := range overrides {
		f(&r)
	}
	return r
}

func TestMatchesFilterRuleEqMatch(t *testing.T) {
	if !MatchesFilterRule(filterRecord(), FilterRule{Field: "record_type", Operator: "eq", Value: "click"}) {
		t.Fatal("expected eq match")
	}
}

func TestMatchesFilterRuleEqNoMatch(t *testing.T) {
	if MatchesFilterRule(filterRecord(), FilterRule{Field: "record_type", Operator: "eq", Value: "pageview"}) {
		t.Fatal("expected no eq match")
	}
}

func TestMatchesFilterRuleNeqMatch(t *testing.T) {
	if !MatchesFilterRule(filterRecord(), FilterRule{Field: "record_type", Operator: "neq", Value: "pageview"}) {
		t.Fatal("expected neq match")
	}
}

func TestMatchesFilterRuleContainsTag(t *testing.T) {
	if !MatchesFilterRule(filterRecord(), FilterRule{Field: "tags", Operator: "contains", Value: "mobile"}) {
		t.Fatal("expected contains tag")
	}
}

func TestMatchesFilterRuleNotContainsTag(t *testing.T) {
	if MatchesFilterRule(filterRecord(), FilterRule{Field: "tags", Operator: "contains", Value: "europe"}) {
		t.Fatal("expected no contains tag")
	}
}

func TestMatchesFilterRuleGtTimestamp(t *testing.T) {
	rule := FilterRule{Field: "ts", Operator: "gt", Value: "2025-06-15T00:00:00Z"}
	if !MatchesFilterRule(filterRecord(func(r *Record) { r.TS = time.Date(2025, 7, 1, 0, 0, 0, 0, time.UTC) }), rule) {
		t.Fatal("expected gt timestamp")
	}
}

func TestMatchesFilterRuleLtTimestamp(t *testing.T) {
	rule := FilterRule{Field: "ts", Operator: "lt", Value: "2025-06-15T00:00:00Z"}
	if !MatchesFilterRule(filterRecord(func(r *Record) { r.TS = time.Date(2025, 5, 1, 0, 0, 0, 0, time.UTC) }), rule) {
		t.Fatal("expected lt timestamp")
	}
}

func TestMatchesFilterRulePayloadEq(t *testing.T) {
	if !MatchesFilterRule(filterRecord(), FilterRule{Field: "payload:url", Operator: "eq", Value: "/home"}) {
		t.Fatal("expected payload eq")
	}
}

func TestMatchesFilterRulePayloadContains(t *testing.T) {
	if !MatchesFilterRule(filterRecord(), FilterRule{Field: "payload:url", Operator: "contains", Value: "home"}) {
		t.Fatal("expected payload contains")
	}
}

func TestMatchesFilterRuleUnknownFieldFalse(t *testing.T) {
	if MatchesFilterRule(filterRecord(), FilterRule{Field: "nonexistent", Operator: "eq", Value: "x"}) {
		t.Fatal("expected unknown field false")
	}
}

func TestMatchesFilterRuleUnknownFieldNeqTrue(t *testing.T) {
	if !MatchesFilterRule(filterRecord(), FilterRule{Field: "nonexistent", Operator: "neq", Value: "x"}) {
		t.Fatal("expected unknown field neq true")
	}
}

func TestApplyFiltersNoRulesReturnsAll(t *testing.T) {
	result := ApplyFilters([]Record{filterRecord(func(r *Record) { r.RecordType = "a" }), filterRecord(func(r *Record) { r.RecordType = "b" })}, nil)
	if len(result) != 2 {
		t.Fatalf("expected all records, got %#v", result)
	}
}

func TestApplyFiltersSingleRule(t *testing.T) {
	records := []Record{
		filterRecord(func(r *Record) { r.RecordType = "click" }),
		filterRecord(func(r *Record) { r.RecordType = "pageview" }),
		filterRecord(func(r *Record) { r.RecordType = "click" }),
	}
	result := ApplyFilters(records, []FilterRule{{Field: "record_type", Operator: "eq", Value: "click"}})
	if len(result) != 2 || result[0].RecordType != "click" || result[1].RecordType != "click" {
		t.Fatalf("unexpected single rule result: %#v", result)
	}
}

func TestApplyFiltersMultipleRulesAnd(t *testing.T) {
	records := []Record{
		filterRecord(func(r *Record) { r.RecordType = "click"; r.Tags = StringSet{"mobile": {}} }),
		filterRecord(func(r *Record) { r.RecordType = "click"; r.Tags = StringSet{"desktop": {}} }),
		filterRecord(func(r *Record) { r.RecordType = "pageview"; r.Tags = StringSet{"mobile": {}} }),
	}
	result := ApplyFilters(records, []FilterRule{{Field: "record_type", Operator: "eq", Value: "click"}, {Field: "tags", Operator: "contains", Value: "mobile"}})
	if len(result) != 1 || result[0].RecordType != "click" {
		t.Fatalf("unexpected AND result: %#v", result)
	}
	if _, ok := result[0].Tags["mobile"]; !ok {
		t.Fatalf("expected mobile tag")
	}
}

func TestApplyFiltersPreservesOrder(t *testing.T) {
	records := []Record{filterRecord(func(r *Record) { r.RecordType = "c" }), filterRecord(func(r *Record) { r.RecordType = "a" }), filterRecord(func(r *Record) { r.RecordType = "b" })}
	result := ApplyFilters(records, []FilterRule{{Field: "record_type", Operator: "neq", Value: "x"}})
	if len(result) != 3 || result[0].RecordType != "c" || result[1].RecordType != "a" || result[2].RecordType != "b" {
		t.Fatalf("order not preserved: %#v", result)
	}
}

func TestApplyFiltersNoMatchYieldsEmpty(t *testing.T) {
	result := ApplyFilters([]Record{filterRecord()}, []FilterRule{{Field: "record_type", Operator: "eq", Value: "nonexistent"}})
	if len(result) != 0 {
		t.Fatalf("expected empty, got %#v", result)
	}
}
