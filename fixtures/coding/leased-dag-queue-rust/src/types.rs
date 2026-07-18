use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct JobSpec {
    pub id: String,
    pub idempotency_key: String,
    pub priority: i32,
    pub dependencies: Vec<String>,
    pub max_attempts: u32,
    pub base_backoff_ms: u64,
}

impl JobSpec {
    pub fn new(id: &str) -> Self {
        Self {
            id: id.to_string(),
            idempotency_key: format!("job:{id}"),
            priority: 0,
            dependencies: Vec::new(),
            max_attempts: 3,
            base_backoff_ms: 100,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum JobState {
    Pending,
    Leased {
        worker: String,
        token: u64,
        expires_at_ms: u64,
    },
    RetryAt(u64),
    Succeeded,
    DeadLettered(String),
    Blocked(String),
    Cancelled,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Lease {
    pub job_id: String,
    pub worker: String,
    pub token: u64,
    pub attempt: u32,
    pub expires_at_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum QueueEvent {
    Enqueued(String),
    Claimed { job_id: String, token: u64 },
    Heartbeat { job_id: String, token: u64 },
    Retrying { job_id: String, ready_at_ms: u64 },
    Succeeded(String),
    DeadLettered(String),
    Blocked { job_id: String, dependency: String },
    Cancelled(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum QueueError {
    DuplicateJob(String),
    IdempotencyConflict(String),
    UnknownDependency(String),
    DependencyCycle,
    UnknownJob(String),
    StaleLease(String),
    InvalidTransition(String),
    NotImplemented,
}

impl fmt::Display for QueueError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for QueueError {}
