use batch_ingestion::{Payload, PayloadValue, Record, StringSet};
use std::collections::{BTreeMap, BTreeSet};
use std::time::{SystemTime, UNIX_EPOCH};

pub fn now_ts() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time before epoch")
        .as_secs() as i64
}

pub fn str_val(value: &str) -> PayloadValue {
    PayloadValue::String(value.to_string())
}

pub fn int_val(value: i64) -> PayloadValue {
    PayloadValue::Int(value)
}

pub fn bool_val(value: bool) -> PayloadValue {
    PayloadValue::Bool(value)
}

pub fn obj_val(items: Vec<(&str, PayloadValue)>) -> PayloadValue {
    PayloadValue::Object(payload(items))
}

pub fn payload(items: Vec<(&str, PayloadValue)>) -> Payload {
    let mut map = BTreeMap::new();
    for (key, value) in items {
        map.insert(key.to_string(), value);
    }
    map
}

pub fn tags(items: &[&str]) -> StringSet {
    items
        .iter()
        .map(|item| item.to_string())
        .collect::<BTreeSet<_>>()
}

pub fn rec(record_type: &str, ts: i64, payload: Payload, tags: &[&str]) -> Record {
    Record {
        record_type: record_type.to_string(),
        ts,
        payload,
        tags: self::tags(tags),
    }
}

pub fn basic_rec() -> Record {
    rec(
        "click",
        now_ts(),
        payload(vec![("page", str_val("/home"))]),
        &["mobile"],
    )
}

pub fn fixed_rec(record_type: &str, payload: Payload) -> Record {
    rec(record_type, 1_735_689_600, payload, &[])
}
