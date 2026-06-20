"""Customer route handlers.

The bulk-import feature is intentionally left as a behavioral stub. It is the
cross-cutting feature used by the maintainability-pressure probe.
"""

from __future__ import annotations

from typing import Any

from service.auth import can_write_customers
from service.models import Customer, Request, Response
from service.validation import normalize_customer_payload, validate_customer_payload


def serialize_customer(customer: Customer) -> dict[str, Any]:
    """Convert a customer model into an API response shape."""
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "plan": customer.plan,
        "tags": list(customer.tags),
    }


def list_customers(request: Request, app: Any) -> Response:
    """List all customers."""
    customers = [serialize_customer(customer) for customer in app.repository.list_customers()]
    return Response(200, {"customers": customers})


def create_customer(request: Request, app: Any) -> Response:
    """Create a single customer through the existing endpoint."""
    if not can_write_customers(request.user):
        return Response(403, {"error": "forbidden"})

    payload = request.json or {}
    errors = validate_customer_payload(payload)
    if errors:
        return Response(400, {"errors": errors})

    normalized = normalize_customer_payload(payload)
    if app.repository.find_by_email(normalized["email"]):
        return Response(409, {"error": "customer already exists"})

    customer = app.repository.create_customer(**normalized)
    return Response(201, {"customer": serialize_customer(customer)})


def bulk_import_customers(request: Request, app: Any) -> Response:
    """Import many customers at once.

    Implement this feature. The correct behavior crosses auth, validation,
    repository, audit, and response-shaping concerns. Keep the existing single
    customer endpoints working.
    """
    return Response(501, {"error": "bulk import not implemented"})
