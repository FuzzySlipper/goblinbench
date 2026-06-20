package pipeline

// Record validation — sign your implementation here.
//
// All function signatures are fixed. Fill the function bodies.

// ValidateRecord checks a single record against all validation rules.
//
// Rules:
//   - RecordType must be non-empty and alphanumeric.
//   - TS must not be in the future (allow 1 s clock skew).
//   - Payload must be non-empty.
//   - Tags may be empty (no rule required).
//
// Return a slice of errors (empty = valid).
func ValidateRecord(record Record) []ValidationError {
	return nil
}

// ValidateBatch splits records into valid and invalid-with-errors.
//
// Invalid records are paired with their validation errors.
// Order of valid records must match input order.
func ValidateBatch(records []Record) ([]Record, []struct {
	Record Record
	Errors []ValidationError
}) {
	return nil, nil
}
