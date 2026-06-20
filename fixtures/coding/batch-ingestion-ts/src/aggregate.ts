/** Record aggregation — sign your implementation here.
 *
 * All function signatures are fixed. Fill the function bodies.
 */

import type { IngestRecord, TypeSummary } from "./types";

export function groupByType(records: IngestRecord[]): Record<string, IngestRecord[]> {
  /**
   * Group records by their recordType field.
   *
   * Preserve insertion order within each group.
   */
  throw new Error("not implemented");
}

export function summarizeType(recordType: string, records: IngestRecord[]): TypeSummary {
  /**
   * Compute aggregate stats for one group.
   *
   *   - count = records.length
   *   - firstTs / lastTs = min/max timestamps
   *   - avgPayloadKeys = mean number of keys in payload
   *
   * If records is empty, return a summary with count=0.
   */
  throw new Error("not implemented");
}

export function aggregateBatch(records: IngestRecord[]): TypeSummary[] {
  /**
   * Group records by type and produce one TypeSummary per type.
   *
   * Types should appear in first-seen order. Return a flat list.
   */
  throw new Error("not implemented");
}
