import { describe, expect, test } from "vitest";
import type { IngestRecord } from "../src/types";
import { groupByType, summarizeType, aggregateBatch } from "../src/aggregate";

const record = (recordType: string, payload: Record<string, unknown> = { k: 1 }, ts = new Date("2025-06-01T00:00:00Z")): IngestRecord => ({
  recordType,
  ts,
  payload,
  tags: new Set<string>(),
});

describe("groupByType", () => {
  test("single type", () => {
    const groups = groupByType([record("click"), record("click")]);
    expect(Object.keys(groups)).toEqual(["click"]);
    expect(groups.click).toHaveLength(2);
  });

  test("multiple types", () => {
    const groups = groupByType([record("click"), record("pageview"), record("click")]);
    expect(new Set(Object.keys(groups))).toEqual(new Set(["click", "pageview"]));
    expect(groups.click).toHaveLength(2);
    expect(groups.pageview).toHaveLength(1);
  });

  test("preserves order within group", () => {
    const groups = groupByType([
      record("a", { n: 1 }, new Date("2025-01-01T00:00:00Z")),
      record("a", { n: 2 }, new Date("2025-06-01T00:00:00Z")),
    ]);
    expect(groups.a?.map((r) => r.payload.n)).toEqual([1, 2]);
  });
});

describe("summarizeType", () => {
  test("single record", () => {
    const ts = new Date("2025-06-01T00:00:00Z");
    const summary = summarizeType("click", [record("click", { a: 1, b: 2 }, ts)]);
    expect(summary.recordType).toBe("click");
    expect(summary.count).toBe(1);
    expect(summary.firstTs?.toISOString()).toBe(ts.toISOString());
    expect(summary.lastTs?.toISOString()).toBe(ts.toISOString());
    expect(summary.avgPayloadKeys).toBe(2.0);
  });

  test("multiple records", () => {
    const summary = summarizeType("click", [
      record("click", { a: 1 }, new Date("2025-01-01T00:00:00Z")),
      record("click", { a: 1, b: 2 }, new Date("2025-06-01T00:00:00Z")),
    ]);
    expect(summary.count).toBe(2);
    expect(summary.firstTs?.toISOString()).toBe("2025-01-01T00:00:00.000Z");
    expect(summary.lastTs?.toISOString()).toBe("2025-06-01T00:00:00.000Z");
    expect(summary.avgPayloadKeys).toBe(1.5);
  });

  test("empty records", () => {
    const summary = summarizeType("empty_type", []);
    expect(summary.recordType).toBe("empty_type");
    expect(summary.count).toBe(0);
    expect(summary.avgPayloadKeys).toBe(0.0);
    expect(summary.firstTs).toBeUndefined();
    expect(summary.lastTs).toBeUndefined();
  });
});

describe("aggregateBatch", () => {
  test("aggregates records by type", () => {
    const summaries = aggregateBatch([record("click"), record("pageview"), record("click")]);
    const typeMap = Object.fromEntries(summaries.map((s) => [s.recordType, s]));
    expect(typeMap.click?.count).toBe(2);
    expect(typeMap.pageview?.count).toBe(1);
  });

  test("uses first-seen type order", () => {
    const summaries = aggregateBatch([record("b"), record("a"), record("c")]);
    expect(summaries.map((s) => s.recordType)).toEqual(["b", "a", "c"]);
  });

  test("empty input", () => {
    expect(aggregateBatch([])).toEqual([]);
  });
});
