use leased_dag_queue::{JobSpec, JobState, LeasedDagQueue, QueueError, QueueEvent};

fn spec(id: &str, priority: i32, dependencies: &[&str]) -> JobSpec {
    JobSpec {
        id: id.to_string(),
        idempotency_key: format!("key:{id}"),
        priority,
        dependencies: dependencies.iter().map(|value| value.to_string()).collect(),
        max_attempts: 3,
        base_backoff_ms: 100,
    }
}

fn claim(queue: &mut LeasedDagQueue, worker: &str, now_ms: u64) -> leased_dag_queue::Lease {
    queue.claim(worker, now_ms, 50).unwrap().expect("ready job")
}

#[test]
fn atomic_admission_accepts_forward_references_and_records_stable_order() {
    let mut queue = LeasedDagQueue::new();
    let ids = queue
        .enqueue_batch(vec![spec("publish", 1, &["build"]), spec("build", 1, &[])])
        .unwrap();

    assert_eq!(ids, ["publish", "build"]);
    assert_eq!(queue.debug_order("publish"), Some(0));
    assert_eq!(queue.debug_order("build"), Some(1));
    assert_eq!(
        queue.events(),
        [
            QueueEvent::Enqueued("publish".into()),
            QueueEvent::Enqueued("build".into())
        ]
    );
}

#[test]
fn rejected_batch_is_fully_atomic_for_unknown_dependencies() {
    let mut queue = LeasedDagQueue::new();
    queue.enqueue_batch(vec![spec("existing", 0, &[])]).unwrap();
    let before_events = queue.events().to_vec();
    let before_counters = queue.counters();

    assert_eq!(
        queue.enqueue_batch(vec![spec("valid", 0, &[]), spec("broken", 0, &["missing"])]),
        Err(QueueError::UnknownDependency("missing".into()))
    );
    assert!(queue.state("valid").is_none());
    assert!(queue.state("broken").is_none());
    assert_eq!(queue.events(), before_events);
    assert_eq!(queue.counters(), before_counters);
}

#[test]
fn rejected_batch_is_fully_atomic_for_cycles() {
    let mut queue = LeasedDagQueue::new();
    assert_eq!(
        queue.enqueue_batch(vec![
            spec("a", 0, &["b"]),
            spec("b", 0, &["c"]),
            spec("c", 0, &["a"])
        ]),
        Err(QueueError::DependencyCycle)
    );
    assert!(queue.events().is_empty());
    assert!(queue.state("a").is_none());
}

#[test]
fn idempotent_replay_returns_original_without_mutating_queue() {
    let mut queue = LeasedDagQueue::new();
    let original = spec("job-a", 4, &[]);
    queue.enqueue_batch(vec![original.clone()]).unwrap();
    let before_events = queue.events().to_vec();
    let before_counters = queue.counters();

    assert_eq!(
        queue.enqueue_batch(vec![original]),
        Ok(vec!["job-a".into()])
    );
    assert_eq!(queue.events(), before_events);
    assert_eq!(queue.counters(), before_counters);
    assert_eq!(queue.idempotent_job("key:job-a"), Some("job-a"));
}

#[test]
fn idempotency_key_cannot_alias_a_different_spec() {
    let mut queue = LeasedDagQueue::new();
    queue.enqueue_batch(vec![spec("first", 0, &[])]).unwrap();
    let mut conflicting = spec("second", 0, &[]);
    conflicting.idempotency_key = "key:first".into();

    assert_eq!(
        queue.enqueue_batch(vec![conflicting]),
        Err(QueueError::IdempotencyConflict("key:first".into()))
    );
    assert!(queue.state("second").is_none());
}

#[test]
fn claim_respects_dependencies_then_priority_then_fifo() {
    let mut queue = LeasedDagQueue::new();
    queue
        .enqueue_batch(vec![
            spec("low", 1, &[]),
            spec("high-first", 9, &[]),
            spec("high-second", 9, &[]),
            spec("blocked-high", 100, &["low"]),
        ])
        .unwrap();

    let first = claim(&mut queue, "worker-a", 10);
    let second = claim(&mut queue, "worker-b", 10);
    assert_eq!(first.job_id, "high-first");
    assert_eq!(second.job_id, "high-second");
    queue.complete(&first.job_id, first.token).unwrap();
    queue.complete(&second.job_id, second.token).unwrap();
    assert_eq!(claim(&mut queue, "worker-a", 11).job_id, "low");
}

#[test]
fn distinct_workers_never_receive_the_same_live_lease() {
    let mut queue = LeasedDagQueue::new();
    queue
        .enqueue_batch(vec![spec("a", 0, &[]), spec("b", 0, &[])])
        .unwrap();

    let a = claim(&mut queue, "one", 0);
    let b = claim(&mut queue, "two", 0);
    assert_ne!(a.job_id, b.job_id);
    assert_ne!(a.token, b.token);
    assert_eq!(queue.claim("three", 0, 50).unwrap(), None);
}

#[test]
fn expired_lease_is_reclaimed_and_old_owner_becomes_stale() {
    let mut queue = LeasedDagQueue::new();
    queue.enqueue_batch(vec![spec("job", 0, &[])]).unwrap();
    let first = claim(&mut queue, "one", 100);
    assert_eq!(queue.claim("two", 149, 50).unwrap(), None);

    let second = claim(&mut queue, "two", 150);
    assert_eq!(second.job_id, "job");
    assert_eq!(second.attempt, 2);
    assert_ne!(second.token, first.token);
    assert_eq!(
        queue.complete("job", first.token),
        Err(QueueError::StaleLease("job".into()))
    );
    queue.complete("job", second.token).unwrap();
    assert_eq!(queue.state("job"), Some(&JobState::Succeeded));
}

#[test]
fn heartbeat_extends_from_observed_time_and_requires_current_token() {
    let mut queue = LeasedDagQueue::new();
    queue.enqueue_batch(vec![spec("job", 0, &[])]).unwrap();
    let lease = claim(&mut queue, "one", 100);
    let renewed = queue.heartbeat("job", lease.token, 130, 80).unwrap();

    assert_eq!(renewed.expires_at_ms, 210);
    assert_eq!(
        queue.heartbeat("job", lease.token + 1, 140, 80),
        Err(QueueError::StaleLease("job".into()))
    );
    assert!(queue.events().contains(&QueueEvent::Heartbeat {
        job_id: "job".into(),
        token: lease.token
    }));
}

#[test]
fn retry_backoff_is_exponential_and_not_claimable_early() {
    let mut queue = LeasedDagQueue::new();
    queue.enqueue_batch(vec![spec("job", 0, &[])]).unwrap();
    let first = claim(&mut queue, "one", 1_000);
    queue
        .fail("job", first.token, 1_010, true, "temporary")
        .unwrap();
    assert_eq!(queue.state("job"), Some(&JobState::RetryAt(1_110)));
    assert_eq!(queue.claim("two", 1_109, 50).unwrap(), None);

    let second = claim(&mut queue, "two", 1_110);
    queue
        .fail("job", second.token, 1_120, true, "temporary")
        .unwrap();
    assert_eq!(queue.state("job"), Some(&JobState::RetryAt(1_320)));
}

#[test]
fn terminal_failure_dead_letters_and_blocks_transitive_dependants() {
    let mut queue = LeasedDagQueue::new();
    queue
        .enqueue_batch(vec![
            spec("root", 0, &[]),
            spec("child", 0, &["root"]),
            spec("grandchild", 0, &["child"]),
        ])
        .unwrap();
    let lease = claim(&mut queue, "one", 0);
    queue
        .fail("root", lease.token, 10, false, "invalid artifact")
        .unwrap();

    assert_eq!(
        queue.state("root"),
        Some(&JobState::DeadLettered("invalid artifact".into()))
    );
    assert_eq!(
        queue.state("child"),
        Some(&JobState::Blocked("root".into()))
    );
    assert_eq!(
        queue.state("grandchild"),
        Some(&JobState::Blocked("child".into()))
    );
    assert_eq!(queue.claim("worker", 100, 50).unwrap(), None);
}

#[test]
fn exhausting_attempt_budget_dead_letters_instead_of_retrying() {
    let mut queue = LeasedDagQueue::new();
    let mut one_try = spec("job", 0, &[]);
    one_try.max_attempts = 1;
    queue.enqueue_batch(vec![one_try]).unwrap();
    let lease = claim(&mut queue, "one", 0);
    queue
        .fail("job", lease.token, 1, true, "still broken")
        .unwrap();

    assert_eq!(
        queue.state("job"),
        Some(&JobState::DeadLettered("still broken".into()))
    );
}

#[test]
fn cancellation_cascades_to_dependants_but_not_unrelated_jobs() {
    let mut queue = LeasedDagQueue::new();
    queue
        .enqueue_batch(vec![
            spec("root", 0, &[]),
            spec("child", 0, &["root"]),
            spec("grandchild", 0, &["child"]),
            spec("unrelated", 0, &[]),
        ])
        .unwrap();
    queue.cancel("root").unwrap();

    assert_eq!(queue.state("root"), Some(&JobState::Cancelled));
    assert_eq!(queue.state("child"), Some(&JobState::Cancelled));
    assert_eq!(queue.state("grandchild"), Some(&JobState::Cancelled));
    assert_eq!(claim(&mut queue, "worker", 0).job_id, "unrelated");
}

#[test]
fn terminal_jobs_reject_repeated_completion_and_cancellation() {
    let mut queue = LeasedDagQueue::new();
    queue.enqueue_batch(vec![spec("job", 0, &[])]).unwrap();
    let lease = claim(&mut queue, "one", 0);
    queue.complete("job", lease.token).unwrap();

    assert_eq!(
        queue.complete("job", lease.token),
        Err(QueueError::InvalidTransition("job".into()))
    );
    assert_eq!(
        queue.cancel("job"),
        Err(QueueError::InvalidTransition("job".into()))
    );
    assert_eq!(queue.attempts("job"), Some(1));
}
