mod common;

use batch_ingestion::{flatten_payload, normalize_payload, transform_batch};
use common::{bool_val, fixed_rec, int_val, obj_val, payload, str_val};

#[test]
fn normalize_payload_snake_case_conversion() {
    let record = fixed_rec(
        "test",
        payload(vec![
            ("UserName", str_val("alice")),
            ("LastLoginCount", int_val(42)),
        ]),
    );
    let result = normalize_payload(&record);
    assert_eq!(result.payload.get("user_name"), Some(&str_val("alice")));
    assert_eq!(result.payload.get("last_login_count"), Some(&int_val(42)));
    assert!(!result.payload.contains_key("UserName"));
}

#[test]
fn normalize_payload_trims_strings() {
    let result = normalize_payload(&fixed_rec(
        "test",
        payload(vec![("name", str_val("  alice  ")), ("num", int_val(42))]),
    ));
    assert_eq!(result.payload.get("name"), Some(&str_val("alice")));
    assert_eq!(result.payload.get("num"), Some(&int_val(42)));
}

#[test]
fn normalize_payload_does_not_mutate_input() {
    let record = fixed_rec("test", payload(vec![("OriginalKey", int_val(1))]));
    let original = record.clone();
    let _ = normalize_payload(&record);
    assert_eq!(record, original);
}

#[test]
fn normalize_payload_empty_payload() {
    let result = normalize_payload(&fixed_rec("test", payload(vec![])));
    assert!(result.payload.is_empty(), "payload={:?}", result.payload);
}

#[test]
fn normalize_payload_already_snake_case() {
    let result = normalize_payload(&fixed_rec(
        "test",
        payload(vec![
            ("already_snake", int_val(1)),
            ("also_ok", str_val("val")),
        ]),
    ));
    assert!(result.payload.contains_key("already_snake"));
    assert!(result.payload.contains_key("also_ok"));
}

#[test]
fn flatten_payload_one_level() {
    let record = fixed_rec(
        "test",
        payload(vec![
            (
                "user",
                obj_val(vec![("name", str_val("alice")), ("id", int_val(7))]),
            ),
            ("page", str_val("/home")),
        ]),
    );
    let result = flatten_payload(&record);
    assert_eq!(result.payload.get("user_name"), Some(&str_val("alice")));
    assert_eq!(result.payload.get("user_id"), Some(&int_val(7)));
    assert_eq!(result.payload.get("page"), Some(&str_val("/home")));
    assert!(!result.payload.contains_key("user"));
}

#[test]
fn flatten_payload_non_object_values_not_flattened() {
    let result = flatten_payload(&fixed_rec(
        "test",
        payload(vec![("count", int_val(5)), ("active", bool_val(true))]),
    ));
    assert_eq!(result.payload.get("count"), Some(&int_val(5)));
    assert_eq!(result.payload.get("active"), Some(&bool_val(true)));
}

#[test]
fn flatten_payload_only_one_level() {
    let record = fixed_rec(
        "test",
        payload(vec![(
            "nested",
            obj_val(vec![
                ("inner", obj_val(vec![("deep", str_val("value"))])),
                ("id", int_val(1)),
            ]),
        )]),
    );
    let result = flatten_payload(&record);
    assert_eq!(result.payload.get("nested_id"), Some(&int_val(1)));
    assert_eq!(
        result.payload.get("nested_inner"),
        Some(&obj_val(vec![("deep", str_val("value"))]))
    );
}

#[test]
fn flatten_payload_does_not_mutate_input() {
    let record = fixed_rec(
        "test",
        payload(vec![
            ("a", obj_val(vec![("b", int_val(1))])),
            ("c", int_val(2)),
        ]),
    );
    let original = record.clone();
    let _ = flatten_payload(&record);
    assert_eq!(record, original);
}

#[test]
fn transform_batch_pipeline() {
    let records = vec![
        fixed_rec(
            "a",
            payload(vec![
                ("User", obj_val(vec![("Name", str_val("alice"))])),
                ("Score", int_val(100)),
            ]),
        ),
        fixed_rec("b", payload(vec![("Item", str_val("book"))])),
    ];
    let results = transform_batch(&records);
    assert_eq!(results.len(), 2);
    assert_eq!(results[0].payload.get("user_name"), Some(&str_val("alice")));
    assert_eq!(results[0].payload.get("score"), Some(&int_val(100)));
}

#[test]
fn transform_batch_preserves_order() {
    let results = transform_batch(&vec![
        fixed_rec("z", payload(vec![("A", int_val(1))])),
        fixed_rec("a", payload(vec![("B", int_val(2))])),
    ]);
    assert_eq!(results.len(), 2);
    assert_eq!(results[0].record_type, "z");
    assert_eq!(results[1].record_type, "a");
}

#[test]
fn transform_batch_does_not_mutate_input() {
    let records = vec![fixed_rec("x", payload(vec![("Key", int_val(1))]))];
    let original = records.clone();
    let _ = transform_batch(&records);
    assert_eq!(records, original);
}
