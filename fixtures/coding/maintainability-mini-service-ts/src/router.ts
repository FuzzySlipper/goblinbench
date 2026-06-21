// Deliberately tempting central router for the maintainability-pressure probe.

import type { AuditLog } from "./audit";
import type { Request, Response } from "./models";
import type { CustomerRepository } from "./repository";

export type Handler = (request: Request, app: Application) => Response;

export class Application {
  private routes = new Map<string, Handler>();

  constructor(
    public readonly repository: CustomerRepository,
    public readonly auditLog: AuditLog,
  ) {}

  addRoute(method: string, path: string, handler: Handler): void {
    this.routes.set(`${method.toUpperCase()} ${path}`, handler);
  }

  handle(request: Request): Response {
    const handler = this.routes.get(`${request.method.toUpperCase()} ${request.path}`);
    if (!handler) {
      return { statusCode: 404, body: { error: "not found" } };
    }
    return handler(request, this);
  }
}
