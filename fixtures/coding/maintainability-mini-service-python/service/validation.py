"""Validation helpers for customer payloads."""

from __future__ import annotations

from typing import Any

ALLOWED_PLANS = {"free", "pro", "enterprise"}


def validate_customer_payload(payload: dict[str, Any]) -> list[str]:
    """Validate the existing single-customer create payload."""
    errors: list[str] = []
    name = payload.get("name")
    email = payload.get("email")
    plan = payload.get("plan", "free")
    tags = payload.get("tags", [])

    if not isinstance(name, str) or not name.strip():
        errors.append("name is required")
    if not isinstance(email, str) or "@" not in email or "." not in email.split("@")[-1]:
        errors.append("email must be valid")
    if plan not in ALLOWED_PLANS:
        errors.append("plan is invalid")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        errors.append("tags must be a list of strings")

    return errors


def normalize_customer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the existing single-customer create payload."""
    return {
        "name": str(payload.get("name", "")).strip(),
        "email": str(payload.get("email", "")).strip().lower(),
        "plan": payload.get("plan", "free"),
        "tags": tuple(str(tag).strip().lower() for tag in payload.get("tags", [])),
    }
