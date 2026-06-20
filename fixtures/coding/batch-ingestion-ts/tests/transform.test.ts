import { describe, expect, test } from "vitest";
import type { IngestRecord } from "../src/types";
import { normalizePayload, flattenPayload, transformBatch } from "../src/transform";

const ts = new Date("2025-01-01T00:00:00Z");
const record = (payload: Record<string, unknown>, recordType = "test"): IngestRecord => ({
  recordType,
  ts,
  payload,
  tags: new Set<string>(),
});

describe("normalizePayload", () => {
  test("converts PascalCase/CamelCase keys to snake_case", () => {
    const result = normalizePayload(record({ UserName: "alice", LastLoginCount: 42 }));
    expect(Object.keys(result.payload)).toContain("user_name");
    expect(Object.keys(result.payload)).toContain("last_login_count");
    expect(Object.keys(result.payload)).not.toContain("UserName");
  });

  test("trims string values", () => {
    const result = normalizePayload(record({ name: "  alice  ", num: 42 }));
    expect(result.payload.name).toBe("alice");
    expect(result.payload.num).toBe(42);
  });

  test("does not mutate input payload", () => {
    const r = record({ OriginalKey: 1 });
    const original = { ...r.payload };
    normalizePayload(r);
    expect(r.payload).toEqual(original);
  });

  test("empty payload remains empty", () => {
    expect(normalizePayload(record({})).payload).toEqual({});
  });

  test("already snake_case keys stay present", () => {
    const result = normalizePayload(record({ already_snake: 1, also_ok: "val" }));
    expect(result.payload).toHaveProperty("already_snake");
    expect(result.payload).toHaveProperty("also_ok");
  });
});

describe("flattenPayload", () => {
  test("flattens one level", () => {
    const result = flattenPayload(record({ user: { name: "alice", id: 7 }, page: "/home" }));
    expect(result.payload.user_name).toBe("alice");
    expect(result.payload.user_id).toBe(7);
    expect(result.payload.page).toBe("/home");
    expect(result.payload).not.toHaveProperty("user");
  });

  test("non-object values are not flattened", () => {
    const result = flattenPayload(record({ count: 5, active: true }));
    expect(result.payload.count).toBe(5);
    expect(result.payload.active).toBe(true);
  });

  test("only flattens one level", () => {
    const result = flattenPayload(record({ nested: { inner: { deep: "value" }, id: 1 } }));
    expect(result.payload).toHaveProperty("nested_inner");
    expect(result.payload.nested_inner).toEqual({ deep: "value" });
  });

  test("arrays and dates are not flattened as plain objects", () => {
    const when = new Date("2025-01-02T00:00:00Z");
    const result = flattenPayload(record({ items: [1, 2], when }));
    expect(result.payload.items).toEqual([1, 2]);
    expect(result.payload.when).toBe(when);
  });

  test("does not mutate input payload", () => {
    const r = record({ a: { b: 1 }, c: 2 });
    const original = { ...r.payload };
    flattenPayload(r);
    expect(r.payload).toEqual(original);
  });
});

describe("transformBatch", () => {
  test("normalizes then flattens every record", () => {
    const records = [
      record({ User: { Name: "alice" }, Score: 100 }, "a"),
      record({ Item: "book" }, "b"),
    ];
    const results = transformBatch(records);
    expect(results).toHaveLength(2);
    expect(results[0]?.payload).toHaveProperty("user_name");
    expect(results[0]?.payload.score).toBe(100);
  });

  test("preserves order", () => {
    const results = transformBatch([record({ A: 1 }, "z"), record({ B: 2 }, "a")]);
    expect(results.map((r) => r.recordType)).toEqual(["z", "a"]);
  });

  test("does not mutate input records", () => {
    const records = [record({ Key: 1 }, "x")];
    transformBatch(records);
    expect(Object.keys(records[0]?.payload ?? {})).toEqual(["Key"]);
  });
});
