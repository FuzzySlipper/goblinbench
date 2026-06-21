use crate::models::JsonMap;

#[derive(Clone, Debug, PartialEq)]
pub struct AuditEvent {
    pub event_type: String,
    pub actor_id: String,
    pub payload: JsonMap,
}

/// Tiny in-memory audit log used by tests and metrics fixtures.
#[derive(Clone, Debug, Default)]
pub struct AuditLog {
    events: Vec<AuditEvent>,
}

impl AuditLog {
    pub fn new() -> Self {
        Self { events: Vec::new() }
    }

    pub fn record(&mut self, event_type: &str, actor_id: &str, payload: JsonMap) {
        self.events.push(AuditEvent {
            event_type: event_type.to_string(),
            actor_id: actor_id.to_string(),
            payload,
        });
    }

    pub fn list_events(&self) -> Vec<AuditEvent> {
        self.events.clone()
    }
}
