package pipeline

import "time"

// Payload is the unstructured payload carried by a record.
type Payload map[string]any

// StringSet is a simple immutable-by-convention string set for record tags.
type StringSet map[string]struct{}

// Record is a single data record flowing through the ingestion pipeline.
//
// DO NOT MODIFY this type. It is part of the fixed interface for the probe.
type Record struct {
	RecordType string
	TS         time.Time
	Payload    Payload
	Tags       StringSet
}

// ValidationError describes why a record failed validation.
//
// DO NOT MODIFY this type. It is part of the fixed interface for the probe.
type ValidationError struct {
	Field  string
	Reason string
}

// TypeSummary is an aggregated summary for one record type.
//
// DO NOT MODIFY this type. It is part of the fixed interface for the probe.
type TypeSummary struct {
	RecordType     string
	Count          int
	FirstTS        *time.Time
	LastTS         *time.Time
	AvgPayloadKeys float64
}

// BatchResult is the final result of a batch ingestion run.
//
// DO NOT MODIFY this type. It is part of the fixed interface for the probe.
type BatchResult struct {
	Ingested  int
	Rejected  int
	Summaries []TypeSummary
}
