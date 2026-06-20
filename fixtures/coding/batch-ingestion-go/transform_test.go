package pipeline

import (
	"reflect"
	"testing"
	"time"
)

func fixedRecord(payload Payload, recordType ...string) Record {
	rt := "test"
	if len(recordType) > 0 {
		rt = recordType[0]
	}
	return Record{RecordType: rt, TS: time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), Payload: payload, Tags: StringSet{}}
}

func TestNormalizePayloadSnakeCaseConversion(t *testing.T) {
	result := NormalizePayload(fixedRecord(Payload{"UserName": "alice", "LastLoginCount": 42}))
	if _, ok := result.Payload["user_name"]; !ok {
		t.Fatalf("missing user_name: %#v", result.Payload)
	}
	if _, ok := result.Payload["last_login_count"]; !ok {
		t.Fatalf("missing last_login_count: %#v", result.Payload)
	}
	if _, ok := result.Payload["UserName"]; ok {
		t.Fatalf("old key still present: %#v", result.Payload)
	}
}

func TestNormalizePayloadTrimsStrings(t *testing.T) {
	result := NormalizePayload(fixedRecord(Payload{"name": "  alice  ", "num": 42}))
	if result.Payload["name"] != "alice" || result.Payload["num"] != 42 {
		t.Fatalf("unexpected payload: %#v", result.Payload)
	}
}

func TestNormalizePayloadDoesNotMutateInput(t *testing.T) {
	r := fixedRecord(Payload{"OriginalKey": 1})
	original := Payload{"OriginalKey": 1}
	NormalizePayload(r)
	if !reflect.DeepEqual(r.Payload, original) {
		t.Fatalf("input mutated: %#v", r.Payload)
	}
}

func TestNormalizePayloadEmptyPayload(t *testing.T) {
	result := NormalizePayload(fixedRecord(Payload{}))
	if len(result.Payload) != 0 {
		t.Fatalf("expected empty payload, got %#v", result.Payload)
	}
}

func TestNormalizePayloadAlreadySnakeCase(t *testing.T) {
	result := NormalizePayload(fixedRecord(Payload{"already_snake": 1, "also_ok": "val"}))
	if _, ok := result.Payload["already_snake"]; !ok {
		t.Fatalf("missing already_snake")
	}
	if _, ok := result.Payload["also_ok"]; !ok {
		t.Fatalf("missing also_ok")
	}
}

func TestFlattenPayloadOneLevel(t *testing.T) {
	result := FlattenPayload(fixedRecord(Payload{"user": map[string]any{"name": "alice", "id": 7}, "page": "/home"}))
	if result.Payload["user_name"] != "alice" || result.Payload["user_id"] != 7 || result.Payload["page"] != "/home" {
		t.Fatalf("unexpected flattened payload: %#v", result.Payload)
	}
	if _, ok := result.Payload["user"]; ok {
		t.Fatalf("old nested key still present: %#v", result.Payload)
	}
}

func TestFlattenPayloadNonMapValuesNotFlattened(t *testing.T) {
	result := FlattenPayload(fixedRecord(Payload{"count": 5, "active": true}))
	if result.Payload["count"] != 5 || result.Payload["active"] != true {
		t.Fatalf("unexpected payload: %#v", result.Payload)
	}
}

func TestFlattenPayloadOnlyOneLevel(t *testing.T) {
	result := FlattenPayload(fixedRecord(Payload{"nested": map[string]any{"inner": map[string]any{"deep": "value"}, "id": 1}}))
	inner, ok := result.Payload["nested_inner"].(map[string]any)
	if !ok || inner["deep"] != "value" {
		t.Fatalf("inner should remain nested, got %#v", result.Payload["nested_inner"])
	}
}

func TestFlattenPayloadDoesNotMutateInput(t *testing.T) {
	r := fixedRecord(Payload{"a": map[string]any{"b": 1}, "c": 2})
	original := Payload{"a": map[string]any{"b": 1}, "c": 2}
	FlattenPayload(r)
	if !reflect.DeepEqual(r.Payload, original) {
		t.Fatalf("input mutated: %#v", r.Payload)
	}
}

func TestTransformBatchPipeline(t *testing.T) {
	records := []Record{
		fixedRecord(Payload{"User": map[string]any{"Name": "alice"}, "Score": 100}, "a"),
		fixedRecord(Payload{"Item": "book"}, "b"),
	}
	results := TransformBatch(records)
	if len(results) != 2 || results[0].Payload["user_name"] != "alice" || results[0].Payload["score"] != 100 {
		t.Fatalf("unexpected transform results: %#v", results)
	}
}

func TestTransformBatchPreservesOrder(t *testing.T) {
	results := TransformBatch([]Record{fixedRecord(Payload{"A": 1}, "z"), fixedRecord(Payload{"B": 2}, "a")})
	if len(results) != 2 || results[0].RecordType != "z" || results[1].RecordType != "a" {
		t.Fatalf("order not preserved: %#v", results)
	}
}

func TestTransformBatchDoesNotMutateInput(t *testing.T) {
	records := []Record{fixedRecord(Payload{"Key": 1}, "x")}
	TransformBatch(records)
	if _, ok := records[0].Payload["Key"]; !ok || len(records[0].Payload) != 1 {
		t.Fatalf("input mutated: %#v", records[0].Payload)
	}
}
