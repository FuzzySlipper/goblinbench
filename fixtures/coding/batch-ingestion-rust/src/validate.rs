use crate::types::{Record, ValidationError};

/// Record validation — sign your implementation here.
///
/// All function signatures are fixed. Fill the function bodies.

/// Validate one record.
///
/// Rules:
/// - `record_type` must be non-empty and alphanumeric.
/// - `ts` must not be more than one second in the future.
/// - `payload` must be non-empty.
///
/// Return all validation errors. Empty vector means valid.
pub fn validate_record(_record: &Record) -> Vec<ValidationError> {
    Vec::new()
}

/// Split records into valid records and invalid records with their errors.
///
/// Preserve input order for valid records.
/// Do NOT mutate input records.
pub fn validate_batch(_records: &[Record]) -> (Vec<Record>, Vec<(Record, Vec<ValidationError>)>) {
    (Vec::new(), Vec::new())
}
