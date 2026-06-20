package pipeline

// Record filtering — sign your implementation here.
//
// All function signatures are fixed. Fill the function bodies.

// FilterRule is a single filter criterion.
type FilterRule struct {
	Field    string
	Operator string // eq, neq, contains, gt, lt
	Value    any
}

// MatchesFilterRule checks whether a record satisfies a single filter rule.
//
// Supported operators:
//   - eq / neq: equality comparison on any field
//   - contains: value (string) in tags OR value in string payload fields
//   - gt / lt: timestamp comparison on TS only, rule value is an RFC3339 string
//
// Field may be: "record_type", "ts", "payload:<key>", "tags".
// Return true if the rule is satisfied.
func MatchesFilterRule(record Record, rule FilterRule) bool {
	return false
}

// ApplyFilters returns only records that satisfy ALL rules (AND logic).
//
// Preserve original order.
// Empty rules list returns all records unchanged.
func ApplyFilters(records []Record, rules []FilterRule) []Record {
	return nil
}
