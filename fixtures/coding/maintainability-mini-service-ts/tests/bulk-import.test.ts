import { describe, expect, test } from "vitest";
import { buildApp } from "../src/container";
import type { Application } from "../src/router";
import type { Request, User } from "../src/models";

const admin = (): User => ({ id: "admin-1", role: "admin" });
const bulkUser = (): User => ({ id: "ops-1", permissions: ["customers:bulk_import"] });

function postBulk(app: Application, rows: unknown, user: User = admin()) {
  return app.handle({ method: "POST", path: "/customers/bulk-import", json: { rows }, user });
}

describe("bulk customer import", () => {
  test("accepts valid rows and returns summary", () => {
    const app = buildApp();
    const response = postBulk(app, [
      { name: "Ada Lovelace", email: "ada@example.com", plan: "pro", tags: ["vip", "math"] },
      { name: "Grace Hopper", email: "GRACE@example.com", plan: "enterprise" },
    ]);

    expect(response.statusCode).toBe(200);
    expect(response.body.accepted_count).toBe(2);
    expect(response.body.rejected_count).toBe(0);
    expect((response.body.accepted as Array<{ email: string }>).map((item) => item.email)).toEqual([
      "ada@example.com",
      "grace@example.com",
    ]);
    expect(response.body.rejected).toEqual([]);
    expect(app.repository.listCustomers().map((customer) => customer.email)).toEqual(["ada@example.com", "grace@example.com"]);
    expect(app.auditLog.listEvents()).toEqual([]);
  });

  test("requires bulk permission and does not mutate state", () => {
    const app = buildApp();
    const response = postBulk(app, [{ name: "Ada", email: "ada@example.com" }], { id: "viewer" });

    expect(response.statusCode).toBe(403);
    expect(response.body).toEqual({ error: "forbidden" });
    expect(app.repository.listCustomers()).toEqual([]);
    expect(app.auditLog.listEvents()).toEqual([]);
  });

  test("accepts dedicated permission without admin role", () => {
    const app = buildApp();
    const response = postBulk(app, [{ name: "Ada", email: "ada@example.com" }], bulkUser());

    expect(response.statusCode).toBe(200);
    expect(response.body.accepted_count).toBe(1);
    expect(app.repository.findByEmail("ada@example.com")).toBeDefined();
  });

  test("rejects invalid rows with indexed errors and audit event", () => {
    const app = buildApp();
    const response = postBulk(app, [
      { name: "", email: "bad", plan: "gold" },
      { name: "Valid Customer", email: "valid@example.com", plan: "free", tags: ["new"] },
      { name: "Bad Tags", email: "tags@example.com", tags: ["ok", 99] },
    ]);

    expect(response.statusCode).toBe(200);
    expect(response.body.accepted_count).toBe(1);
    expect(response.body.rejected_count).toBe(2);
    expect((response.body.accepted as Array<{ email: string }>)[0]?.email).toBe("valid@example.com");

    const rejected = response.body.rejected as Array<{ index: number; email: string; errors: string[] }>;
    expect(rejected[0]?.index).toBe(0);
    expect(rejected[0]?.errors).toContain("name is required");
    expect(rejected[0]?.errors).toContain("email must be valid");
    expect(rejected[0]?.errors).toContain("plan is invalid");
    expect(rejected[1]).toEqual({ index: 2, email: "tags@example.com", errors: ["tags must be a list of strings"] });

    const events = app.auditLog.listEvents();
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      type: "customers.bulk_import.rejected",
      actorId: "admin-1",
      payload: { accepted_count: 1, rejected_count: 2 },
    });
  });

  test("rejects existing and in-batch duplicate emails", () => {
    const app = buildApp();
    app.handle({ method: "POST", path: "/customers", json: { name: "Existing", email: "existing@example.com" }, user: admin() });

    const response = postBulk(app, [
      { name: "Existing Again", email: "existing@example.com" },
      { name: "First", email: "dupe@example.com" },
      { name: "Second", email: "DUPE@example.com" },
    ]);

    expect(response.statusCode).toBe(200);
    expect(response.body.accepted_count).toBe(1);
    expect((response.body.accepted as Array<{ email: string }>)[0]?.email).toBe("dupe@example.com");
    expect(response.body.rejected).toEqual([
      { index: 0, email: "existing@example.com", errors: ["customer already exists"] },
      { index: 2, email: "dupe@example.com", errors: ["duplicate email in import"] },
    ]);
    expect(app.repository.listCustomers().map((customer) => customer.email)).toEqual(["existing@example.com", "dupe@example.com"]);
  });

  test("rejects missing or non-list rows payload", () => {
    const app = buildApp();

    const missing = app.handle({ method: "POST", path: "/customers/bulk-import", json: {}, user: admin() });
    expect(missing.statusCode).toBe(400);
    expect(missing.body).toEqual({ error: "rows must be a list" });

    const wrongType = app.handle({ method: "POST", path: "/customers/bulk-import", json: { rows: "not-list" }, user: admin() });
    expect(wrongType.statusCode).toBe(400);
    expect(wrongType.body).toEqual({ error: "rows must be a list" });
  });

  test("preserves existing list route after import", () => {
    const app = buildApp();
    postBulk(app, [{ name: "Ada", email: "ada@example.com" }, { name: "Grace", email: "grace@example.com" }]);

    const listed = app.handle({ method: "GET", path: "/customers", user: admin() });
    expect(listed.statusCode).toBe(200);
    expect((listed.body.customers as Array<{ email: string }>).map((customer) => customer.email)).toEqual([
      "ada@example.com",
      "grace@example.com",
    ]);
  });
});
