mod common;

use batch_ingestion::{aggregate_batch, group_by_type, summarize_type};
use common::{int_val, payload, rec};

fn aggregate_record(
    record_type: &str,
    payload_items: Vec<(&str, batch_ingestion::PayloadValue)>,
    ts: i64,
) -> batch_ingestion::Record {
    rec(record_type, ts, payload(payload_items), &[])
}

#[test]
fn group_by_type_single_type() {
    let groups = group_by_type(&[
        aggregate_record("click", vec![("k", int_val(1))], 1),
        aggregate_record("click", vec![("k", int_val(2))], 2),
    ]);
    assert_eq!(groups.len(), 1);
    assert_eq!(groups.get("click").map(Vec::len), Some(2));
}

#[test]
fn group_by_type_multiple_types() {
    let groups = group_by_type(&[
        aggregate_record("click", vec![("k", int_val(1))], 1),
        aggregate_record("pageview", vec![("k", int_val(2))], 2),
        aggregate_record("click", vec![("k", int_val(3))], 3),
    ]);
    assert_eq!(groups.len(), 2);
    assert_eq!(groups.get("click").map(Vec::len), Some(2));
    assert_eq!(groups.get("pageview").map(Vec::len), Some(1));
}

#[test]
fn group_by_type_preserves_order_within_group() {
    let groups = group_by_type(&[
        aggregate_record("a", vec![("n", int_val(1))], 10),
        aggregate_record("a", vec![("n", int_val(2))], 20),
    ]);
    let group = groups.get("a").expect("missing group a");
    assert_eq!(group.len(), 2);
    assert_eq!(group[0].payload.get("n"), Some(&int_val(1)));
    assert_eq!(group[1].payload.get("n"), Some(&int_val(2)));
}

#[test]
fn summarize_type_single_record() {
    let summary = summarize_type(
        "click",
        &[aggregate_record(
            "click",
            vec![("a", int_val(1)), ("b", int_val(2))],
            100,
        )],
    );
    assert_eq!(summary.record_type, "click");
    assert_eq!(summary.count, 1);
    assert_eq!(summary.first_ts, Some(100));
    assert_eq!(summary.last_ts, Some(100));
    assert_eq!(summary.avg_payload_keys, 2.0);
}

#[test]
fn summarize_type_multiple_records() {
    let summary = summarize_type(
        "click",
        &[
            aggregate_record("click", vec![("a", int_val(1))], 100),
            aggregate_record("click", vec![("a", int_val(1)), ("b", int_val(2))], 200),
        ],
    );
    assert_eq!(summary.count, 2);
    assert_eq!(summary.first_ts, Some(100));
    assert_eq!(summary.last_ts, Some(200));
    assert_eq!(summary.avg_payload_keys, 1.5);
}

#[test]
fn summarize_type_empty() {
    let summary = summarize_type("empty_type", &[]);
    assert_eq!(summary.record_type, "empty_type");
    assert_eq!(summary.count, 0);
    assert_eq!(summary.first_ts, None);
    assert_eq!(summary.last_ts, None);
    assert_eq!(summary.avg_payload_keys, 0.0);
}

#[test]
fn aggregate_batch_groups_counts() {
    let summaries = aggregate_batch(&[
        aggregate_record("click", vec![("k", int_val(1))], 1),
        aggregate_record("pageview", vec![("k", int_val(2))], 2),
        aggregate_record("click", vec![("k", int_val(3))], 3),
    ]);
    let click = summaries
        .iter()
        .find(|summary| summary.record_type == "click")
        .expect("missing click");
    let pageview = summaries
        .iter()
        .find(|summary| summary.record_type == "pageview")
        .expect("missing pageview");
    assert_eq!(click.count, 2);
    assert_eq!(pageview.count, 1);
}

#[test]
fn aggregate_batch_first_seen_order() {
    let summaries = aggregate_batch(&[
        aggregate_record("b", vec![("k", int_val(1))], 1),
        aggregate_record("a", vec![("k", int_val(2))], 2),
        aggregate_record("c", vec![("k", int_val(3))], 3),
    ]);
    assert_eq!(summaries.len(), 3);
    assert_eq!(summaries[0].record_type, "b");
    assert_eq!(summaries[1].record_type, "a");
    assert_eq!(summaries[2].record_type, "c");
}

#[test]
fn aggregate_batch_empty() {
    let summaries = aggregate_batch(&[]);
    assert!(summaries.is_empty(), "summaries={summaries:?}");
}
