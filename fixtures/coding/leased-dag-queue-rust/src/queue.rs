use std::collections::HashMap;

use crate::types::{JobSpec, JobState, Lease, QueueError, QueueEvent};

#[derive(Clone, Debug)]
struct JobRecord {
    spec: JobSpec,
    state: JobState,
    attempts: u32,
    enqueue_order: u64,
}

#[derive(Default)]
pub struct LeasedDagQueue {
    jobs: HashMap<String, JobRecord>,
    idempotency: HashMap<String, String>,
    events: Vec<QueueEvent>,
    next_order: u64,
    next_token: u64,
}

impl LeasedDagQueue {
    pub fn new() -> Self {
        Self::default()
    }

    /// Admit a graph fragment atomically. Replaying an identical idempotency key
    /// and specification returns the original job id without another event.
    pub fn enqueue_batch(&mut self, _specs: Vec<JobSpec>) -> Result<Vec<String>, QueueError> {
        Err(QueueError::NotImplemented)
    }

    /// Claim the highest-priority ready job, using admission order as the tie-breaker.
    pub fn claim(
        &mut self,
        _worker: &str,
        _now_ms: u64,
        _lease_ms: u64,
    ) -> Result<Option<Lease>, QueueError> {
        Err(QueueError::NotImplemented)
    }

    pub fn heartbeat(
        &mut self,
        _job_id: &str,
        _token: u64,
        _now_ms: u64,
        _lease_ms: u64,
    ) -> Result<Lease, QueueError> {
        Err(QueueError::NotImplemented)
    }

    pub fn complete(&mut self, _job_id: &str, _token: u64) -> Result<(), QueueError> {
        Err(QueueError::NotImplemented)
    }

    pub fn fail(
        &mut self,
        _job_id: &str,
        _token: u64,
        _now_ms: u64,
        _retryable: bool,
        _reason: &str,
    ) -> Result<(), QueueError> {
        Err(QueueError::NotImplemented)
    }

    /// Cancel a non-terminal job and all of its transitive dependants.
    pub fn cancel(&mut self, _job_id: &str) -> Result<(), QueueError> {
        Err(QueueError::NotImplemented)
    }

    pub fn state(&self, job_id: &str) -> Option<&JobState> {
        self.jobs.get(job_id).map(|record| &record.state)
    }

    pub fn attempts(&self, job_id: &str) -> Option<u32> {
        self.jobs.get(job_id).map(|record| record.attempts)
    }

    pub fn events(&self) -> &[QueueEvent] {
        &self.events
    }

    pub fn admitted_spec(&self, job_id: &str) -> Option<&JobSpec> {
        self.jobs.get(job_id).map(|record| &record.spec)
    }

    pub fn debug_order(&self, job_id: &str) -> Option<u64> {
        self.jobs.get(job_id).map(|record| record.enqueue_order)
    }

    pub fn idempotent_job(&self, key: &str) -> Option<&str> {
        self.idempotency.get(key).map(String::as_str)
    }

    pub fn counters(&self) -> (u64, u64) {
        (self.next_order, self.next_token)
    }
}
