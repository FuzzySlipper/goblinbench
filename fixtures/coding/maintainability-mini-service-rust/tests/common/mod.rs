#![allow(dead_code)]

use maintainability_mini_service::*;

pub fn admin_user() -> User {
    User {
        id: "admin-1".to_string(),
        role: "admin".to_string(),
        permissions: Vec::new(),
    }
}

pub fn bulk_user() -> User {
    User {
        id: "ops-1".to_string(),
        role: "member".to_string(),
        permissions: vec!["customers:bulk_import".to_string()],
    }
}

pub fn request(method: &str, path: &str, json: JsonMap, user: User) -> Request {
    Request {
        method: method.to_string(),
        path: path.to_string(),
        json,
        user: Some(user),
    }
}

pub fn customer_payload(name: &str, email: &str, plan: Option<&str>, tags: Vec<&str>) -> JsonValue {
    let mut entries = vec![("name", text(name)), ("email", text(email))];
    if let Some(plan) = plan {
        entries.push(("plan", text(plan)));
    }
    if !tags.is_empty() {
        entries.push(("tags", array(tags.into_iter().map(text).collect())));
    }
    object(entries)
}

pub fn post_bulk(app: &mut Application, rows: JsonValue, user: User) -> Response {
    app.handle(request(
        "POST",
        "/customers/bulk-import",
        map(vec![("rows", rows)]),
        user,
    ))
}

pub fn get_array<'a>(map: &'a JsonMap, key: &str) -> &'a [JsonValue] {
    match map.get(key) {
        Some(JsonValue::Array(values)) => values,
        other => panic!("expected {key} array, got {other:?}"),
    }
}

pub fn get_object<'a>(value: &'a JsonValue) -> &'a JsonMap {
    match value {
        JsonValue::Object(map) => map,
        other => panic!("expected object, got {other:?}"),
    }
}

pub fn get_string<'a>(map: &'a JsonMap, key: &str) -> &'a str {
    match map.get(key) {
        Some(JsonValue::String(value)) => value,
        other => panic!("expected {key} string, got {other:?}"),
    }
}

pub fn assert_errors_contain(errors: &[JsonValue], want: &str) {
    assert!(
        errors
            .iter()
            .any(|value| matches!(value, JsonValue::String(text) if text == want)),
        "{want:?} missing from {errors:?}"
    );
}
