use std::collections::BTreeMap;

use crate::audit::AuditLog;
use crate::models::{Request, Response, map, text};
use crate::repository::CustomerRepository;

pub type Handler = fn(Request, &mut Application) -> Response;

/// Minimal route dispatcher with shared repository/audit dependencies.
pub struct Application {
    pub repository: CustomerRepository,
    pub audit_log: AuditLog,
    routes: BTreeMap<String, Handler>,
}

impl Application {
    pub fn new(repository: CustomerRepository, audit_log: AuditLog) -> Self {
        Self {
            repository,
            audit_log,
            routes: BTreeMap::new(),
        }
    }

    pub fn add_route(&mut self, method: &str, path: &str, handler: Handler) {
        self.routes
            .insert(format!("{} {}", method.to_uppercase(), path), handler);
    }

    pub fn handle(&mut self, request: Request) -> Response {
        match self.routes.get(&format!(
            "{} {}",
            request.method.to_uppercase(),
            request.path
        )) {
            Some(handler) => handler(request, self),
            None => Response {
                status_code: 404,
                body: map(vec![("error", text("not found"))]),
            },
        }
    }
}
