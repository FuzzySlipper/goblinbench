package pipeline

// Record transformation — sign your implementation here.
//
// All function signatures are fixed. Fill the function bodies.

// NormalizePayload normalises payload keys to snake_case.
//
// For every key in Payload:
//   - Convert PascalCase/CamelCase keys to snake_case.
//   - Trim whitespace from string values.
//   - Leave non-string values unchanged.
//
// Return a new Record with the transformed payload.
// Do NOT mutate the input record, payload, or tags.
func NormalizePayload(record Record) Record {
	return Record{}
}

// FlattenPayload flattens one level of nested map values in Payload.
//
// e.g. {"user": {"name": "alice", "id": 7}} becomes
// {"user_name": "alice", "user_id": 7, ...other keys}
//
// Only flatten one level. Non-map values stay as-is.
// Return a new Record with the flattened payload.
func FlattenPayload(record Record) Record {
	return Record{}
}

// TransformBatch applies NormalizePayload then FlattenPayload to every record.
//
// Return new records in the original order.
func TransformBatch(records []Record) []Record {
	return nil
}
