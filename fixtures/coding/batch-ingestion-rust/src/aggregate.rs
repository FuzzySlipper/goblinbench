use crate::types::{Record, TypeSummary};
use std::collections::BTreeMap;

/// Record aggregation — sign your implementation here.
///
/// All function signatures are fixed. Fill the function bodies.

/// Group records by `record_type`.
///
/// Preserve insertion order within each group.
pub fn group_by_type(_records: &[Record]) -> BTreeMap<String, Vec<Record>> {
    BTreeMap::new()
}

/// Summarize one record-type group.
///
/// - `count` is the number of records.
/// - `first_ts` / `last_ts` are min/max timestamps.
/// - `avg_payload_keys` is the mean payload key count.
pub fn summarize_type(_record_type: &str, _records: &[Record]) -> TypeSummary {
    TypeSummary {
        record_type: String::new(),
        count: 0,
        first_ts: None,
        last_ts: None,
        avg_payload_keys: 0.0,
    }
}

/// Aggregate a batch into one summary per record type.
///
/// Types should appear in first-seen order.
pub fn aggregate_batch(_records: &[Record]) -> Vec<TypeSummary> {
    Vec::new()
}
