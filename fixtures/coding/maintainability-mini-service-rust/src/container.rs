use crate::audit::AuditLog;
use crate::customers::{bulk_import_customers, create_customer, list_customers};
use crate::repository::CustomerRepository;
use crate::router::Application;

/// Builds the mini application and registers routes.
pub fn build_app() -> Application {
    let mut app = Application::new(CustomerRepository::new(), AuditLog::new());
    app.add_route("GET", "/customers", list_customers);
    app.add_route("POST", "/customers", create_customer);
    app.add_route("POST", "/customers/bulk-import", bulk_import_customers);
    app
}
