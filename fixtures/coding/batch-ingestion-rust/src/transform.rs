use crate::types::{Payload, Record};

/// Record transformation — sign your implementation here.
///
/// All function signatures are fixed. Fill the function bodies.

/// Normalize payload keys to snake_case and trim string payload values.
///
/// Return a new record. Do NOT mutate the input record, payload, or tags.
pub fn normalize_payload(_record: &Record) -> Record {
    Record {
        record_type: String::new(),
        ts: 0,
        payload: Payload::new(),
        tags: Default::default(),
    }
}

/// Flatten one level of nested object payload values.
///
/// `{ "user": Object({"name": "alice"}) }` becomes `{ "user_name": "alice" }`.
/// Only flatten one level. Non-object values stay as-is.
pub fn flatten_payload(_record: &Record) -> Record {
    Record {
        record_type: String::new(),
        ts: 0,
        payload: Payload::new(),
        tags: Default::default(),
    }
}

/// Apply `normalize_payload` and then `flatten_payload` to every record.
///
/// Preserve input order.
pub fn transform_batch(_records: &[Record]) -> Vec<Record> {
    Vec::new()
}
