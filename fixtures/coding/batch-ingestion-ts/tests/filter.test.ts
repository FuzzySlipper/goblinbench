import { describe, expect, test } from "vitest";
import type { IngestRecord } from "../src/types";
import type { FilterRule } from "../src/filter";
import { matchesFilterRule, applyFilters } from "../src/filter";

const record = (overrides: Partial<IngestRecord> = {}): IngestRecord => ({
  recordType: "click",
  ts: new Date("2025-06-01T00:00:00Z"),
  payload: { url: "/home", count: 5 },
  tags: new Set(["mobile", "us-east"]),
  ...overrides,
});

describe("matchesFilterRule", () => {
  test("eq match", () => {
    expect(matchesFilterRule(record(), { field: "recordType", operator: "eq", value: "click" })).toBe(true);
  });

  test("eq no match", () => {
    expect(matchesFilterRule(record(), { field: "recordType", operator: "eq", value: "pageview" })).toBe(false);
  });

  test("neq match", () => {
    expect(matchesFilterRule(record(), { field: "recordType", operator: "neq", value: "pageview" })).toBe(true);
  });

  test("contains tag", () => {
    expect(matchesFilterRule(record(), { field: "tags", operator: "contains", value: "mobile" })).toBe(true);
  });

  test("not contains tag", () => {
    expect(matchesFilterRule(record(), { field: "tags", operator: "contains", value: "europe" })).toBe(false);
  });

  test("gt timestamp", () => {
    const rule: FilterRule = { field: "ts", operator: "gt", value: "2025-06-15T00:00:00Z" };
    expect(matchesFilterRule(record({ ts: new Date("2025-07-01T00:00:00Z") }), rule)).toBe(true);
  });

  test("lt timestamp", () => {
    const rule: FilterRule = { field: "ts", operator: "lt", value: "2025-06-15T00:00:00Z" };
    expect(matchesFilterRule(record({ ts: new Date("2025-05-01T00:00:00Z") }), rule)).toBe(true);
  });

  test("payload field eq", () => {
    expect(matchesFilterRule(record(), { field: "payload:url", operator: "eq", value: "/home" })).toBe(true);
  });

  test("payload field contains", () => {
    expect(matchesFilterRule(record(), { field: "payload:url", operator: "contains", value: "home" })).toBe(true);
  });

  test("unknown field returns false", () => {
    expect(matchesFilterRule(record(), { field: "nonexistent", operator: "eq", value: "x" })).toBe(false);
  });

  test("unknown field neq returns true", () => {
    expect(matchesFilterRule(record(), { field: "nonexistent", operator: "neq", value: "x" })).toBe(true);
  });
});

describe("applyFilters", () => {
  test("no rules returns all", () => {
    expect(applyFilters([record({ recordType: "a" }), record({ recordType: "b" })], [])).toHaveLength(2);
  });

  test("single rule", () => {
    const records = [record({ recordType: "click" }), record({ recordType: "pageview" }), record({ recordType: "click" })];
    const result = applyFilters(records, [{ field: "recordType", operator: "eq", value: "click" }]);
    expect(result).toHaveLength(2);
    expect(result.every((r) => r.recordType === "click")).toBe(true);
  });

  test("multiple rules use AND logic", () => {
    const records = [
      record({ recordType: "click", tags: new Set(["mobile"]) }),
      record({ recordType: "click", tags: new Set(["desktop"]) }),
      record({ recordType: "pageview", tags: new Set(["mobile"]) }),
    ];
    const result = applyFilters(records, [
      { field: "recordType", operator: "eq", value: "click" },
      { field: "tags", operator: "contains", value: "mobile" },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]?.recordType).toBe("click");
    expect(result[0]?.tags.has("mobile")).toBe(true);
  });

  test("preserves order", () => {
    const records = [record({ recordType: "c" }), record({ recordType: "a" }), record({ recordType: "b" })];
    const result = applyFilters(records, [{ field: "recordType", operator: "neq", value: "x" }]);
    expect(result.map((r) => r.recordType)).toEqual(["c", "a", "b"]);
  });

  test("no match yields empty", () => {
    expect(applyFilters([record()], [{ field: "recordType", operator: "eq", value: "nonexistent" }])).toEqual([]);
  });
});
