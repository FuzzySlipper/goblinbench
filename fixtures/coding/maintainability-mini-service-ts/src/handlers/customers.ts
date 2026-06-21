// Customer route handlers.
//
// The bulk-import feature is intentionally left as a behavioral stub. It is the
// cross-cutting feature used by the maintainability-pressure probe.

import { canWriteCustomers } from "../auth";
import type { Application } from "../router";
import type { Customer, Request, Response } from "../models";
import { normalizeCustomerPayload, validateCustomerPayload } from "../validation";

export function serializeCustomer(customer: Customer): Record<string, unknown> {
  return {
    id: customer.id,
    name: customer.name,
    email: customer.email,
    plan: customer.plan,
    tags: [...customer.tags],
  };
}

export function listCustomers(_request: Request, app: Application): Response {
  const customers = app.repository.listCustomers().map((customer) => serializeCustomer(customer));
  return { statusCode: 200, body: { customers } };
}

export function createCustomer(request: Request, app: Application): Response {
  if (!canWriteCustomers(request.user)) {
    return { statusCode: 403, body: { error: "forbidden" } };
  }

  const payload = request.json ?? {};
  const errors = validateCustomerPayload(payload);
  if (errors.length > 0) {
    return { statusCode: 400, body: { errors } };
  }

  const normalized = normalizeCustomerPayload(payload);
  if (app.repository.findByEmail(normalized.email)) {
    return { statusCode: 409, body: { error: "customer already exists" } };
  }

  const customer = app.repository.createCustomer(normalized.name, normalized.email, normalized.plan, normalized.tags);
  return { statusCode: 201, body: { customer: serializeCustomer(customer) } };
}

export function bulkImportCustomers(_request: Request, _app: Application): Response {
  // Implement this feature. The correct behavior crosses auth, validation,
  // repository, audit, and response-shaping concerns. Keep the existing single
  // customer endpoints working.
  return { statusCode: 501, body: { error: "bulk import not implemented" } };
}
