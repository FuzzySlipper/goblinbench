"""In-memory customer repository used by the fixture tests."""

from __future__ import annotations

from service.models import Customer


class CustomerRepository:
    """Small repository with deterministic IDs for testability."""

    def __init__(self) -> None:
        self._customers: list[Customer] = []
        self._next_id = 1

    def list_customers(self) -> list[Customer]:
        return list(self._customers)

    def find_by_email(self, email: str) -> Customer | None:
        normalized = email.strip().lower()
        return next((customer for customer in self._customers if customer.email == normalized), None)

    def create_customer(self, name: str, email: str, plan: str, tags: tuple[str, ...] = ()) -> Customer:
        customer = Customer(
            id=f"cus_{self._next_id}",
            name=name,
            email=email.strip().lower(),
            plan=plan,
            tags=tuple(tags),
        )
        self._next_id += 1
        self._customers.append(customer)
        return customer
