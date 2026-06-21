// Validation helpers for customer payloads.

import type { Plan } from "./models";

const ALLOWED_PLANS = new Set<Plan>(["free", "pro", "enterprise"]);

export interface NormalizedCustomerPayload {
  name: string;
  email: string;
  plan: Plan;
  tags: readonly string[];
}

export function validateCustomerPayload(payload: Record<string, unknown>): string[] {
  const errors: string[] = [];
  const name = payload.name;
  const email = payload.email;
  const plan = payload.plan ?? "free";
  const tags = payload.tags ?? [];

  if (typeof name !== "string" || name.trim() === "") {
    errors.push("name is required");
  }
  if (typeof email !== "string" || !email.includes("@") || !email.split("@").at(-1)?.includes(".")) {
    errors.push("email must be valid");
  }
  if (typeof plan !== "string" || !ALLOWED_PLANS.has(plan as Plan)) {
    errors.push("plan is invalid");
  }
  if (!Array.isArray(tags) || !tags.every((tag) => typeof tag === "string")) {
    errors.push("tags must be a list of strings");
  }

  return errors;
}

export function normalizeCustomerPayload(payload: Record<string, unknown>): NormalizedCustomerPayload {
  const tags = Array.isArray(payload.tags) ? payload.tags : [];
  return {
    name: String(payload.name ?? "").trim(),
    email: String(payload.email ?? "").trim().toLowerCase(),
    plan: (payload.plan ?? "free") as Plan,
    tags: tags.map((tag) => String(tag).trim().toLowerCase()),
  };
}
