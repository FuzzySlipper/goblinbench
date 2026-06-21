// Fixed request/response and domain model types for the mini service.

export type Plan = "free" | "pro" | "enterprise";

export interface User {
  id: string;
  role?: "viewer" | "admin" | string;
  permissions?: readonly string[];
}

export interface Request {
  method: string;
  path: string;
  json?: Record<string, unknown>;
  user?: User;
}

export interface Response {
  statusCode: number;
  body: Record<string, unknown>;
}

export interface Customer {
  id: string;
  name: string;
  email: string;
  plan: Plan;
  tags: readonly string[];
}
