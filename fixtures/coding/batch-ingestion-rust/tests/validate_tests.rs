mod common;

use batch_ingestion::{validate_batch, validate_record};
use common::{basic_rec, int_val, now_ts, payload, rec, str_val};

fn has_field(errors: &[batch_ingestion::ValidationError], field: &str) -> bool {
    errors.iter().any(|error| error.field == field)
}

#[test]
fn validate_record_valid_passes() {
    let errors = validate_record(&basic_rec());
    assert!(errors.is_empty(), "expected no errors, got {errors:?}");
}

#[test]
fn validate_record_empty_type_fails() {
    let mut record = basic_rec();
    record.record_type.clear();
    let errors = validate_record(&record);
    assert!(has_field(&errors, "record_type"), "got {errors:?}");
}

#[test]
fn validate_record_non_alphanumeric_type_fails() {
    let mut record = basic_rec();
    record.record_type = "click/event!".to_string();
    let errors = validate_record(&record);
    assert!(has_field(&errors, "record_type"), "got {errors:?}");
}

#[test]
fn validate_record_future_timestamp_fails() {
    let mut record = basic_rec();
    record.ts = now_ts() + 7_200;
    let errors = validate_record(&record);
    assert!(has_field(&errors, "ts"), "got {errors:?}");
}

#[test]
fn validate_record_near_future_allows_one_second_skew() {
    let mut record = basic_rec();
    record.ts = now_ts() + 1;
    let errors = validate_record(&record);
    assert!(!has_field(&errors, "ts"), "got {errors:?}");
}

#[test]
fn validate_record_empty_payload_fails() {
    let mut record = basic_rec();
    record.payload.clear();
    let errors = validate_record(&record);
    assert!(has_field(&errors, "payload"), "got {errors:?}");
}

#[test]
fn validate_record_multiple_errors() {
    let mut record = basic_rec();
    record.record_type.clear();
    record.ts = now_ts() + 86_400;
    record.payload.clear();
    let errors = validate_record(&record);
    assert!(errors.len() >= 3, "got {errors:?}");
    assert!(has_field(&errors, "record_type"));
    assert!(has_field(&errors, "ts"));
    assert!(has_field(&errors, "payload"));
}

#[test]
fn validate_record_does_not_mutate_input() {
    let record = rec(
        "test",
        now_ts(),
        payload(vec![("key", str_val("val"))]),
        &["a"],
    );
    let original = record.clone();
    let _ = validate_record(&record);
    assert_eq!(record, original);
}

#[test]
fn validate_batch_all_valid() {
    let records = vec![
        rec("a", now_ts(), payload(vec![("x", int_val(1))]), &[]),
        rec("b", now_ts(), payload(vec![("y", int_val(2))]), &[]),
    ];
    let (valid, invalid) = validate_batch(&records);
    assert_eq!(valid.len(), 2);
    assert!(invalid.is_empty(), "invalid={invalid:?}");
}

#[test]
fn validate_batch_some_invalid() {
    let records = vec![
        rec(
            "valid",
            now_ts(),
            payload(vec![("ok", str_val("yes"))]),
            &[],
        ),
        rec(
            "",
            now_ts(),
            payload(vec![("bad", str_val("empty-type"))]),
            &[],
        ),
        rec(
            "valid2",
            now_ts(),
            payload(vec![("ok", str_val("no"))]),
            &[],
        ),
    ];
    let (valid, invalid) = validate_batch(&records);
    assert_eq!(valid.len(), 2, "valid={valid:?}");
    assert_eq!(invalid.len(), 1, "invalid={invalid:?}");
    assert_eq!(invalid[0].0.record_type, "");
}

#[test]
fn validate_batch_preserves_order() {
    let records = vec![
        rec("x", now_ts(), payload(vec![("n", int_val(1))]), &[]),
        rec("bad!", now_ts(), payload(vec![("n", int_val(2))]), &[]),
        rec("y", now_ts(), payload(vec![("n", int_val(3))]), &[]),
    ];
    let (valid, _) = validate_batch(&records);
    assert_eq!(valid.len(), 2);
    assert_eq!(valid[0].payload.get("n"), Some(&int_val(1)));
    assert_eq!(valid[1].payload.get("n"), Some(&int_val(3)));
}

#[test]
fn validate_batch_does_not_mutate_input() {
    let records = vec![rec(
        "test",
        now_ts(),
        payload(vec![("k", str_val("v"))]),
        &["a"],
    )];
    let original = records.clone();
    let _ = validate_batch(&records);
    assert_eq!(records, original);
}

#[test]
fn validate_batch_large_input() {
    let records: Vec<_> = (0..50)
        .map(|idx| {
            rec(
                &format!("type{idx}"),
                now_ts(),
                payload(vec![("idx", int_val(idx))]),
                &[],
            )
        })
        .collect();
    let (valid, invalid) = validate_batch(&records);
    assert_eq!(valid.len(), 50);
    assert!(invalid.is_empty());
}
