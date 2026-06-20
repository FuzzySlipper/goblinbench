package pipeline

import (
	"testing"
	"time"
)

func aggregateRecord(recordType string, payload Payload, ts ...time.Time) Record {
	when := time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC)
	if len(ts) > 0 {
		when = ts[0]
	}
	if payload == nil {
		payload = Payload{"k": 1}
	}
	return Record{RecordType: recordType, TS: when, Payload: payload, Tags: StringSet{}}
}

func TestGroupByTypeSingleType(t *testing.T) {
	groups := GroupByType([]Record{aggregateRecord("click", nil), aggregateRecord("click", nil)})
	if len(groups) != 1 || len(groups["click"]) != 2 {
		t.Fatalf("unexpected groups: %#v", groups)
	}
}

func TestGroupByTypeMultipleTypes(t *testing.T) {
	groups := GroupByType([]Record{aggregateRecord("click", nil), aggregateRecord("pageview", nil), aggregateRecord("click", nil)})
	if len(groups) != 2 || len(groups["click"]) != 2 || len(groups["pageview"]) != 1 {
		t.Fatalf("unexpected groups: %#v", groups)
	}
}

func TestGroupByTypePreservesOrderWithinGroup(t *testing.T) {
	groups := GroupByType([]Record{
		aggregateRecord("a", Payload{"n": 1}, time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)),
		aggregateRecord("a", Payload{"n": 2}, time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC)),
	})
	group := groups["a"]
	if len(group) != 2 || group[0].Payload["n"] != 1 || group[1].Payload["n"] != 2 {
		t.Fatalf("group order not preserved: %#v", group)
	}
}

func TestSummarizeTypeSingleRecord(t *testing.T) {
	ts := time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC)
	summary := SummarizeType("click", []Record{aggregateRecord("click", Payload{"a": 1, "b": 2}, ts)})
	if summary.RecordType != "click" || summary.Count != 1 || summary.FirstTS == nil || summary.LastTS == nil || !summary.FirstTS.Equal(ts) || !summary.LastTS.Equal(ts) || summary.AvgPayloadKeys != 2.0 {
		t.Fatalf("unexpected summary: %#v", summary)
	}
}

func TestSummarizeTypeMultipleRecords(t *testing.T) {
	ts1 := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	ts2 := time.Date(2025, 6, 1, 0, 0, 0, 0, time.UTC)
	summary := SummarizeType("click", []Record{aggregateRecord("click", Payload{"a": 1}, ts1), aggregateRecord("click", Payload{"a": 1, "b": 2}, ts2)})
	if summary.Count != 2 || summary.FirstTS == nil || summary.LastTS == nil || !summary.FirstTS.Equal(ts1) || !summary.LastTS.Equal(ts2) || summary.AvgPayloadKeys != 1.5 {
		t.Fatalf("unexpected summary: %#v", summary)
	}
}

func TestSummarizeTypeEmpty(t *testing.T) {
	summary := SummarizeType("empty_type", nil)
	if summary.RecordType != "empty_type" || summary.Count != 0 || summary.AvgPayloadKeys != 0.0 || summary.FirstTS != nil || summary.LastTS != nil {
		t.Fatalf("unexpected empty summary: %#v", summary)
	}
}

func TestAggregateBatch(t *testing.T) {
	summaries := AggregateBatch([]Record{aggregateRecord("click", nil), aggregateRecord("pageview", nil), aggregateRecord("click", nil)})
	typeMap := map[string]TypeSummary{}
	for _, summary := range summaries {
		typeMap[summary.RecordType] = summary
	}
	if typeMap["click"].Count != 2 || typeMap["pageview"].Count != 1 {
		t.Fatalf("unexpected summaries: %#v", summaries)
	}
}

func TestAggregateBatchFirstSeenOrder(t *testing.T) {
	summaries := AggregateBatch([]Record{aggregateRecord("b", nil), aggregateRecord("a", nil), aggregateRecord("c", nil)})
	if len(summaries) != 3 || summaries[0].RecordType != "b" || summaries[1].RecordType != "a" || summaries[2].RecordType != "c" {
		t.Fatalf("order not preserved: %#v", summaries)
	}
}

func TestAggregateBatchEmpty(t *testing.T) {
	if summaries := AggregateBatch(nil); len(summaries) != 0 {
		t.Fatalf("expected empty, got %#v", summaries)
	}
}
