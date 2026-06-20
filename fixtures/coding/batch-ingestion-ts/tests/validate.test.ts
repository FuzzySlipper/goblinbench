import { describe, expect, test } from "vitest";
import type { IngestRecord } from "../src/types";
import { validateRecord, validateBatch } from "../src/validate";

const record = (overrides: Partial<IngestRecord> = {}): IngestRecord => ({
  recordType: "click",
  ts: new Date(),
  payload: { page: "/home" },
  tags: new Set(["mobile"]),
  ...overrides,
});

describe("validateRecord", () => {
  test("valid record passes", () => {
    expect(validateRecord(record())).toEqual([]);
  });

  test("empty recordType fails", () => {
    const errors = validateRecord(record({ recordType: "" }));
    expect(errors.some((e) => e.field === "recordType")).toBe(true);
  });

  test("non-alphanumeric recordType fails", () => {
    const errors = validateRecord(record({ recordType: "click/event!" }));
    expect(errors.some((e) => e.field === "recordType")).toBe(true);
  });

  test("future timestamp fails", () => {
    const errors = validateRecord(record({ ts: new Date(Date.now() + 2 * 60 * 60 * 1000) }));
    expect(errors.some((e) => e.field === "ts")).toBe(true);
  });

  test("near-future timestamp allows one second skew", () => {
    const errors = validateRecord(record({ ts: new Date(Date.now() + 900) }));
    expect(errors.filter((e) => e.field === "ts")).toHaveLength(0);
  });

  test("empty payload fails", () => {
    const errors = validateRecord(record({ payload: {} }));
    expect(errors.some((e) => e.field === "payload")).toBe(true);
  });

  test("multiple errors on invalid record", () => {
    const errors = validateRecord(record({
      recordType: "",
      ts: new Date(Date.now() + 24 * 60 * 60 * 1000),
      payload: {},
    }));
    expect(errors.length).toBeGreaterThanOrEqual(3);
    const fields = new Set(errors.map((e) => e.field));
    expect(fields.has("recordType")).toBe(true);
    expect(fields.has("ts")).toBe(true);
    expect(fields.has("payload")).toBe(true);
  });

  test("validation does not mutate input", () => {
    const tags = new Set(["a"]);
    const r = record({ recordType: "test", payload: { key: "val" }, tags });
    const original = JSON.stringify({
      recordType: r.recordType,
      ts: r.ts.toISOString(),
      payload: r.payload,
      tags: [...r.tags],
    });
    validateRecord(r);
    expect(JSON.stringify({
      recordType: r.recordType,
      ts: r.ts.toISOString(),
      payload: r.payload,
      tags: [...r.tags],
    })).toBe(original);
  });
});

describe("validateBatch", () => {
  test("all valid", () => {
    const records = [record({ recordType: "a", payload: { x: 1 } }), record({ recordType: "b", payload: { y: 2 } })];
    const [valid, invalid] = validateBatch(records);
    expect(valid).toHaveLength(2);
    expect(invalid).toHaveLength(0);
  });

  test("some invalid", () => {
    const records = [
      record({ recordType: "valid", payload: { ok: true } }),
      record({ recordType: "", payload: { bad: "empty-type" } }),
      record({ recordType: "valid2", payload: { ok: false } }),
    ];
    const [valid, invalid] = validateBatch(records);
    expect(valid).toHaveLength(2);
    expect(invalid).toHaveLength(1);
    expect(invalid[0]?.[0].recordType).toBe("");
  });

  test("preserves valid-record order", () => {
    const records = [
      record({ recordType: "x", payload: { n: 1 } }),
      record({ recordType: "bad!", payload: { n: 2 } }),
      record({ recordType: "y", payload: { n: 3 } }),
    ];
    const [valid] = validateBatch(records);
    expect(valid.map((r) => r.payload.n)).toEqual([1, 3]);
  });

  test("does not mutate input array or records", () => {
    const records = [record({ recordType: "test", payload: { k: "v" } })];
    validateBatch(records);
    expect(records[0]?.recordType).toBe("test");
    expect(records[0]?.payload).toEqual({ k: "v" });
  });

  test("large input", () => {
    const records = Array.from({ length: 50 }, (_, i) => record({ recordType: `type${i}`, payload: { idx: i } }));
    const [valid, invalid] = validateBatch(records);
    expect(valid).toHaveLength(50);
    expect(invalid).toHaveLength(0);
  });
});
