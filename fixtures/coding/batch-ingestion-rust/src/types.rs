use std::collections::{BTreeMap, BTreeSet};

/// A deterministic string set used for record tags.
pub type StringSet = BTreeSet<String>;

/// A deterministic payload map carried by records.
pub type Payload = BTreeMap<String, PayloadValue>;

/// Fixed payload value enum for the style probe.
///
/// DO NOT MODIFY this enum. It is part of the fixed interface.
#[derive(Clone, Debug, PartialEq)]
pub enum PayloadValue {
    String(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    Object(BTreeMap<String, PayloadValue>),
    Null,
}

/// A single record flowing through the ingestion pipeline.
///
/// `ts` is a Unix timestamp in seconds. DO NOT MODIFY this type.
#[derive(Clone, Debug, PartialEq)]
pub struct Record {
    pub record_type: String,
    pub ts: i64,
    pub payload: Payload,
    pub tags: StringSet,
}

/// Describes why a record failed validation.
///
/// DO NOT MODIFY this type.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidationError {
    pub field: String,
    pub reason: String,
}

/// Aggregate summary for one record type.
///
/// DO NOT MODIFY this type.
#[derive(Clone, Debug, PartialEq)]
pub struct TypeSummary {
    pub record_type: String,
    pub count: usize,
    pub first_ts: Option<i64>,
    pub last_ts: Option<i64>,
    pub avg_payload_keys: f64,
}

/// Final batch result shape for downstream consumers.
///
/// DO NOT MODIFY this type.
#[derive(Clone, Debug, PartialEq)]
pub struct BatchResult {
    pub ingested: usize,
    pub rejected: usize,
    pub summaries: Vec<TypeSummary>,
}
