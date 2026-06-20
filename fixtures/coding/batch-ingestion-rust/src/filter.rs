use crate::types::{PayloadValue, Record};

/// A single filter criterion.
#[derive(Clone, Debug, PartialEq)]
pub struct FilterRule {
    pub field: String,
    pub operator: String, // eq, neq, contains, gt, lt
    pub value: PayloadValue,
}

/// Check whether one record satisfies one filter rule.
///
/// Supported operators:
/// - eq / neq: equality comparison on any supported field.
/// - contains: string in tags OR substring in string payload field.
/// - gt / lt: timestamp comparison on `ts`, with integer rule value.
///
/// Field may be: `record_type`, `ts`, `payload:<key>`, or `tags`.
pub fn matches_filter_rule(_record: &Record, _rule: &FilterRule) -> bool {
    false
}

/// Return records that satisfy ALL rules (AND logic).
///
/// Empty rules returns all records unchanged. Preserve order.
pub fn apply_filters(_records: &[Record], _rules: &[FilterRule]) -> Vec<Record> {
    Vec::new()
}
