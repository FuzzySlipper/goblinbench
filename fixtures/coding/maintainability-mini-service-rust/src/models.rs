use std::collections::BTreeMap;

/// Tiny JSON-like value type used by the in-memory request/response fixtures.
#[derive(Clone, Debug, PartialEq)]
pub enum JsonValue {
    String(String),
    Number(i64),
    Bool(bool),
    Object(BTreeMap<String, JsonValue>),
    Array(Vec<JsonValue>),
    Null,
}

pub type JsonMap = BTreeMap<String, JsonValue>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct User {
    pub id: String,
    pub role: String,
    pub permissions: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Request {
    pub method: String,
    pub path: String,
    pub json: JsonMap,
    pub user: Option<User>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Response {
    pub status_code: u16,
    pub body: JsonMap,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Customer {
    pub id: String,
    pub name: String,
    pub email: String,
    pub plan: String,
    pub tags: Vec<String>,
}

pub fn text(value: &str) -> JsonValue {
    JsonValue::String(value.to_string())
}

pub fn number(value: i64) -> JsonValue {
    JsonValue::Number(value)
}

pub fn array(values: Vec<JsonValue>) -> JsonValue {
    JsonValue::Array(values)
}

pub fn map(entries: Vec<(&str, JsonValue)>) -> JsonMap {
    entries
        .into_iter()
        .map(|(key, value)| (key.to_string(), value))
        .collect()
}

pub fn object(entries: Vec<(&str, JsonValue)>) -> JsonValue {
    JsonValue::Object(map(entries))
}
