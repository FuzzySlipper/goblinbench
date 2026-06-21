use crate::models::{JsonMap, JsonValue};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NormalizedCustomerPayload {
    pub name: String,
    pub email: String,
    pub plan: String,
    pub tags: Vec<String>,
}

/// Validates the existing single-customer create payload.
pub fn validate_customer_payload(payload: &JsonMap) -> Vec<String> {
    let mut errors = Vec::new();
    let name = string_field(payload, "name");
    let email = string_field(payload, "email");
    let plan = string_field(payload, "plan").unwrap_or("free");

    if name.is_none_or(|value| value.trim().is_empty()) {
        errors.push("name is required".to_string());
    }
    if email.is_none_or(|value| !is_valid_email(value)) {
        errors.push("email must be valid".to_string());
    }
    if !matches!(plan, "free" | "pro" | "enterprise") {
        errors.push("plan is invalid".to_string());
    }
    if !tags_are_strings(payload.get("tags")) {
        errors.push("tags must be a list of strings".to_string());
    }

    errors
}

/// Normalizes the existing single-customer create payload.
pub fn normalize_customer_payload(payload: &JsonMap) -> NormalizedCustomerPayload {
    NormalizedCustomerPayload {
        name: string_field(payload, "name")
            .unwrap_or_default()
            .trim()
            .to_string(),
        email: string_field(payload, "email")
            .unwrap_or_default()
            .trim()
            .to_lowercase(),
        plan: string_field(payload, "plan").unwrap_or("free").to_string(),
        tags: normalize_tags(payload.get("tags")),
    }
}

pub fn string_field<'a>(payload: &'a JsonMap, key: &str) -> Option<&'a str> {
    match payload.get(key) {
        Some(JsonValue::String(value)) => Some(value),
        _ => None,
    }
}

fn is_valid_email(email: &str) -> bool {
    let Some((local, domain)) = email.split_once('@') else {
        return false;
    };
    !local.is_empty() && domain.contains('.')
}

fn tags_are_strings(value: Option<&JsonValue>) -> bool {
    match value {
        None => true,
        Some(JsonValue::Array(values)) => values
            .iter()
            .all(|value| matches!(value, JsonValue::String(_))),
        _ => false,
    }
}

fn normalize_tags(value: Option<&JsonValue>) -> Vec<String> {
    let Some(JsonValue::Array(values)) = value else {
        return Vec::new();
    };
    values
        .iter()
        .filter_map(|value| match value {
            JsonValue::String(text) => Some(text.trim().to_lowercase()),
            _ => None,
        })
        .collect()
}
