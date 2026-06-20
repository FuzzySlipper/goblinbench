"""Application setup and dependency wiring."""

from __future__ import annotations

from service.audit import AuditLog
from service.handlers.customers import bulk_import_customers, create_customer, list_customers
from service.repository import CustomerRepository
from service.router import Application


def build_app() -> Application:
    """Build the mini application and register routes."""
    app = Application(repository=CustomerRepository(), audit_log=AuditLog())
    app.add_route("GET", "/customers", list_customers)
    app.add_route("POST", "/customers", create_customer)
    app.add_route("POST", "/customers/bulk-import", bulk_import_customers)
    return app
