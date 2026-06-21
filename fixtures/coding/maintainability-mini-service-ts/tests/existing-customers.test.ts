import { describe, expect, test } from "vitest";
import { buildApp } from "../src/container";
import type { User } from "../src/models";

const admin = (): User => ({ id: "admin-1", role: "admin" });

describe("existing customer routes", () => {
  test("create and list customer flow still works", () => {
    const app = buildApp();

    const create = app.handle({
      method: "POST",
      path: "/customers",
      json: { name: "Ada Lovelace", email: "Ada@Example.COM", plan: "pro", tags: ["VIP"] },
      user: admin(),
    });

    expect(create.statusCode).toBe(201);
    const customer = create.body.customer as { email: string; tags: string[] };
    expect(customer.email).toBe("ada@example.com");
    expect(customer.tags).toEqual(["vip"]);

    const listed = app.handle({ method: "GET", path: "/customers", user: admin() });
    expect(listed.statusCode).toBe(200);
    expect((listed.body.customers as Array<{ email: string }>).map((item) => item.email)).toEqual(["ada@example.com"]);
  });

  test("create customer rejects invalid payload", () => {
    const app = buildApp();
    const response = app.handle({ method: "POST", path: "/customers", json: { name: "", email: "bad", plan: "gold" }, user: admin() });

    expect(response.statusCode).toBe(400);
    expect(response.body.errors).toContain("name is required");
    expect(response.body.errors).toContain("email must be valid");
    expect(response.body.errors).toContain("plan is invalid");
  });

  test("create customer requires permission", () => {
    const app = buildApp();
    const response = app.handle({ method: "POST", path: "/customers", json: { name: "Grace", email: "grace@example.com" }, user: { id: "viewer" } });

    expect(response.statusCode).toBe(403);
    expect(app.repository.listCustomers()).toEqual([]);
  });
});
