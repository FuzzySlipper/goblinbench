use std::collections::HashMap;

use crate::types::{JobSpec, QueueError};

/// Validate all dependency references and cycles before queue state is changed.
pub fn validate_admission(
    _existing: &HashMap<String, JobSpec>,
    _batch: &[JobSpec],
) -> Result<(), QueueError> {
    Err(QueueError::NotImplemented)
}
