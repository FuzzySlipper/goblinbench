mod common;

use batch_ingestion::{FilterRule, apply_filters, matches_filter_rule};
use common::{fixed_rec, int_val, payload, rec, str_val};

fn filter_record() -> batch_ingestion::Record {
    rec(
        "click",
        1_748_736_000,
        payload(vec![("url", str_val("/home")), ("count", int_val(5))]),
        &["mobile", "us-east"],
    )
}

fn rule(field: &str, operator: &str, value: batch_ingestion::PayloadValue) -> FilterRule {
    FilterRule {
        field: field.to_string(),
        operator: operator.to_string(),
        value,
    }
}

#[test]
fn matches_filter_rule_eq_match() {
    assert!(matches_filter_rule(
        &filter_record(),
        &rule("record_type", "eq", str_val("click"))
    ));
}

#[test]
fn matches_filter_rule_eq_no_match() {
    assert!(!matches_filter_rule(
        &filter_record(),
        &rule("record_type", "eq", str_val("pageview"))
    ));
}

#[test]
fn matches_filter_rule_neq_match() {
    assert!(matches_filter_rule(
        &filter_record(),
        &rule("record_type", "neq", str_val("pageview"))
    ));
}

#[test]
fn matches_filter_rule_contains_tag() {
    assert!(matches_filter_rule(
        &filter_record(),
        &rule("tags", "contains", str_val("mobile"))
    ));
}

#[test]
fn matches_filter_rule_not_contains_tag() {
    assert!(!matches_filter_rule(
        &filter_record(),
        &rule("tags", "contains", str_val("europe"))
    ));
}

#[test]
fn matches_filter_rule_gt_timestamp() {
    let record = rec(
        "click",
        1_750_000_000,
        payload(vec![("url", str_val("/home"))]),
        &[],
    );
    assert!(matches_filter_rule(
        &record,
        &rule("ts", "gt", int_val(1_748_736_000))
    ));
}

#[test]
fn matches_filter_rule_lt_timestamp() {
    let record = rec(
        "click",
        1_700_000_000,
        payload(vec![("url", str_val("/home"))]),
        &[],
    );
    assert!(matches_filter_rule(
        &record,
        &rule("ts", "lt", int_val(1_748_736_000))
    ));
}

#[test]
fn matches_filter_rule_payload_eq() {
    assert!(matches_filter_rule(
        &filter_record(),
        &rule("payload:url", "eq", str_val("/home"))
    ));
}

#[test]
fn matches_filter_rule_payload_contains() {
    assert!(matches_filter_rule(
        &filter_record(),
        &rule("payload:url", "contains", str_val("home"))
    ));
}

#[test]
fn matches_filter_rule_unknown_field_false() {
    assert!(!matches_filter_rule(
        &filter_record(),
        &rule("nonexistent", "eq", str_val("x"))
    ));
}

#[test]
fn matches_filter_rule_unknown_field_neq_true() {
    assert!(matches_filter_rule(
        &filter_record(),
        &rule("nonexistent", "neq", str_val("x"))
    ));
}

#[test]
fn apply_filters_no_rules_returns_all() {
    let records = vec![
        fixed_rec("a", payload(vec![("n", int_val(1))])),
        fixed_rec("b", payload(vec![("n", int_val(2))])),
    ];
    let result = apply_filters(&records, &[]);
    assert_eq!(result, records);
}

#[test]
fn apply_filters_single_rule() {
    let records = vec![
        fixed_rec("click", payload(vec![("n", int_val(1))])),
        fixed_rec("pageview", payload(vec![("n", int_val(2))])),
        fixed_rec("click", payload(vec![("n", int_val(3))])),
    ];
    let result = apply_filters(&records, &[rule("record_type", "eq", str_val("click"))]);
    assert_eq!(result.len(), 2);
    assert_eq!(result[0].record_type, "click");
    assert_eq!(result[1].record_type, "click");
}

#[test]
fn apply_filters_multiple_rules_and() {
    let records = vec![
        rec("click", 1, payload(vec![("n", int_val(1))]), &["mobile"]),
        rec("click", 2, payload(vec![("n", int_val(2))]), &["desktop"]),
        rec("pageview", 3, payload(vec![("n", int_val(3))]), &["mobile"]),
    ];
    let result = apply_filters(
        &records,
        &[
            rule("record_type", "eq", str_val("click")),
            rule("tags", "contains", str_val("mobile")),
        ],
    );
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].record_type, "click");
    assert!(result[0].tags.contains("mobile"));
}

#[test]
fn apply_filters_preserves_order() {
    let records = vec![
        fixed_rec("c", payload(vec![])),
        fixed_rec("a", payload(vec![])),
        fixed_rec("b", payload(vec![])),
    ];
    let result = apply_filters(&records, &[rule("record_type", "neq", str_val("x"))]);
    assert_eq!(result.len(), 3);
    assert_eq!(result[0].record_type, "c");
    assert_eq!(result[1].record_type, "a");
    assert_eq!(result[2].record_type, "b");
}

#[test]
fn apply_filters_no_match_yields_empty() {
    let result = apply_filters(
        &[filter_record()],
        &[rule("record_type", "eq", str_val("nonexistent"))],
    );
    assert!(result.is_empty(), "result={result:?}");
}
