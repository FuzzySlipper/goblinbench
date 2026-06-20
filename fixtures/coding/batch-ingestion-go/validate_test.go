package pipeline

import (
	"testing"
	"time"
)

func rec(overrides ...func(*Record)) Record {
	r := Record{
		RecordType: "click",
		TS:         time.Now().UTC(),
		Payload:    Payload{"page": "/home"},
		Tags:       StringSet{"mobile": {}},
	}
	for _, f := range overrides {
		f(&r)
	}
	return r
}

func hasField(errors []ValidationError, field string) bool {
	for _, err := range errors {
		if err.Field == field {
			return true
		}
	}
	return false
}

func TestValidateRecordValidPasses(t *testing.T) {
	if errors := ValidateRecord(rec()); len(errors) != 0 {
		t.Fatalf("expected no errors, got %#v", errors)
	}
}

func TestValidateRecordEmptyTypeFails(t *testing.T) {
	errors := ValidateRecord(rec(func(r *Record) { r.RecordType = "" }))
	if !hasField(errors, "record_type") {
		t.Fatalf("expected record_type error, got %#v", errors)
	}
}

func TestValidateRecordNonAlphanumericTypeFails(t *testing.T) {
	errors := ValidateRecord(rec(func(r *Record) { r.RecordType = "click/event!" }))
	if !hasField(errors, "record_type") {
		t.Fatalf("expected record_type error, got %#v", errors)
	}
}

func TestValidateRecordFutureTimestampFails(t *testing.T) {
	errors := ValidateRecord(rec(func(r *Record) { r.TS = time.Now().UTC().Add(2 * time.Hour) }))
	if !hasField(errors, "ts") {
		t.Fatalf("expected ts error, got %#v", errors)
	}
}

func TestValidateRecordNearFutureAllowsOneSecondSkew(t *testing.T) {
	errors := ValidateRecord(rec(func(r *Record) { r.TS = time.Now().UTC().Add(900 * time.Millisecond) }))
	if hasField(errors, "ts") {
		t.Fatalf("expected no ts error, got %#v", errors)
	}
}

func TestValidateRecordEmptyPayloadFails(t *testing.T) {
	errors := ValidateRecord(rec(func(r *Record) { r.Payload = Payload{} }))
	if !hasField(errors, "payload") {
		t.Fatalf("expected payload error, got %#v", errors)
	}
}

func TestValidateRecordMultipleErrors(t *testing.T) {
	errors := ValidateRecord(rec(func(r *Record) {
		r.RecordType = ""
		r.TS = time.Now().UTC().Add(24 * time.Hour)
		r.Payload = Payload{}
	}))
	if len(errors) < 3 || !hasField(errors, "record_type") || !hasField(errors, "ts") || !hasField(errors, "payload") {
		t.Fatalf("expected record_type, ts, payload errors, got %#v", errors)
	}
}

func TestValidateRecordDoesNotMutateInput(t *testing.T) {
	tags := StringSet{"a": {}}
	r := rec(func(r *Record) {
		r.RecordType = "test"
		r.Payload = Payload{"key": "val"}
		r.Tags = tags
	})
	ValidateRecord(r)
	if r.RecordType != "test" || r.Payload["key"] != "val" {
		t.Fatalf("record mutated: %#v", r)
	}
	if _, ok := r.Tags["a"]; !ok || len(r.Tags) != 1 {
		t.Fatalf("tags mutated: %#v", r.Tags)
	}
}

func TestValidateBatchAllValid(t *testing.T) {
	records := []Record{
		rec(func(r *Record) { r.RecordType = "a"; r.Payload = Payload{"x": 1} }),
		rec(func(r *Record) { r.RecordType = "b"; r.Payload = Payload{"y": 2} }),
	}
	valid, invalid := ValidateBatch(records)
	if len(valid) != 2 || len(invalid) != 0 {
		t.Fatalf("expected 2 valid/0 invalid, got %d/%d", len(valid), len(invalid))
	}
}

func TestValidateBatchSomeInvalid(t *testing.T) {
	records := []Record{
		rec(func(r *Record) { r.RecordType = "valid"; r.Payload = Payload{"ok": true} }),
		rec(func(r *Record) { r.RecordType = ""; r.Payload = Payload{"bad": "empty-type"} }),
		rec(func(r *Record) { r.RecordType = "valid2"; r.Payload = Payload{"ok": false} }),
	}
	valid, invalid := ValidateBatch(records)
	if len(valid) != 2 || len(invalid) != 1 || invalid[0].Record.RecordType != "" {
		t.Fatalf("unexpected split: valid=%#v invalid=%#v", valid, invalid)
	}
}

func TestValidateBatchPreservesOrder(t *testing.T) {
	records := []Record{
		rec(func(r *Record) { r.RecordType = "x"; r.Payload = Payload{"n": 1} }),
		rec(func(r *Record) { r.RecordType = "bad!"; r.Payload = Payload{"n": 2} }),
		rec(func(r *Record) { r.RecordType = "y"; r.Payload = Payload{"n": 3} }),
	}
	valid, _ := ValidateBatch(records)
	if len(valid) != 2 || valid[0].Payload["n"] != 1 || valid[1].Payload["n"] != 3 {
		t.Fatalf("valid order not preserved: %#v", valid)
	}
}

func TestValidateBatchDoesNotMutateInput(t *testing.T) {
	records := []Record{rec(func(r *Record) { r.RecordType = "test"; r.Payload = Payload{"k": "v"} })}
	ValidateBatch(records)
	if records[0].RecordType != "test" || records[0].Payload["k"] != "v" {
		t.Fatalf("input mutated: %#v", records)
	}
}

func TestValidateBatchLargeInput(t *testing.T) {
	records := make([]Record, 50)
	for i := range records {
		i := i
		records[i] = rec(func(r *Record) { r.RecordType = "type" + string(rune('A'+i%26)); r.Payload = Payload{"idx": i} })
	}
	valid, invalid := ValidateBatch(records)
	if len(valid) != 50 || len(invalid) != 0 {
		t.Fatalf("expected 50 valid/0 invalid, got %d/%d", len(valid), len(invalid))
	}
}
