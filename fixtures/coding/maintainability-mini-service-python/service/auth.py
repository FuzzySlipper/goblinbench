"""Authorization helpers for customer operations."""

from __future__ import annotations

from service.models import User


WRITE_CUSTOMERS = "customers:write"
BULK_IMPORT_CUSTOMERS = "customers:bulk_import"


def can_write_customers(user: User | None) -> bool:
    """Return whether a user can create individual customers."""
    return bool(user and (user.role == "admin" or WRITE_CUSTOMERS in user.permissions))


def can_bulk_import_customers(user: User | None) -> bool:
    """Return whether a user can bulk-import customers."""
    return bool(user and (user.role == "admin" or BULK_IMPORT_CUSTOMERS in user.permissions))
