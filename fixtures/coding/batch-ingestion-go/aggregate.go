package pipeline

// Record aggregation — sign your implementation here.
//
// All function signatures are fixed. Fill the function bodies.

// GroupByType groups records by their RecordType field.
//
// Preserve insertion order within each group.
func GroupByType(records []Record) map[string][]Record {
	return nil
}

// SummarizeType computes aggregate stats for one group.
//
//   - Count = len(records)
//   - FirstTS / LastTS = min/max timestamps
//   - AvgPayloadKeys = mean number of keys in payload
//
// If records is empty, return a summary with Count=0.
func SummarizeType(recordType string, records []Record) TypeSummary {
	return TypeSummary{}
}

// AggregateBatch groups records by type and produces one TypeSummary per type.
//
// Types should appear in first-seen order. Return a flat slice.
func AggregateBatch(records []Record) []TypeSummary {
	return nil
}
