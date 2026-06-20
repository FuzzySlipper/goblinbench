"""Deliberately tempting central router for the maintainability-pressure probe."""

from __future__ import annotations

from collections.abc import Callable

from service.audit import AuditLog
from service.models import Request, Response
from service.repository import CustomerRepository

Handler = Callable[[Request, "Application"], Response]


class Application:
    """Minimal route dispatcher with shared repository/audit dependencies."""

    def __init__(self, repository: CustomerRepository, audit_log: AuditLog) -> None:
        self.repository = repository
        self.audit_log = audit_log
        self._routes: dict[tuple[str, str], Handler] = {}

    def add_route(self, method: str, path: str, handler: Handler) -> None:
        self._routes[(method.upper(), path)] = handler

    def handle(self, request: Request) -> Response:
        handler = self._routes.get((request.method.upper(), request.path))
        if handler is None:
            return Response(404, {"error": "not found"})
        return handler(request, self)
