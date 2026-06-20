/** Record filtering — sign your implementation here.
 *
 * All function signatures are fixed. Fill the function bodies.
 */

import type { IngestRecord } from "./types";

export interface FilterRule {
  readonly field: string;
  readonly operator: "eq" | "neq" | "contains" | "gt" | "lt";
  readonly value: unknown;
}

export function matchesFilterRule(record: IngestRecord, rule: FilterRule): boolean {
  /**
   * Check whether a record satisfies a single filter rule.
   *
   * Supported operators:
   *   - eq / neq: equality comparison on any field
   *   - contains: value (string) in tags OR value in string payload fields
   *   - gt / lt: timestamp comparison on ts only, rule value is ISO string
   *
   * field may be: "recordType", "ts", "payload:<key>", "tags"
   * Return true if the rule is satisfied.
   */
  throw new Error("not implemented");
}

export function applyFilters(records: IngestRecord[], rules: FilterRule[]): IngestRecord[] {
  /**
   * Return only records that satisfy ALL rules (AND logic).
   *
   * Preserve original order.
   * Empty rules list → return all records unchanged.
   */
  throw new Error("not implemented");
}
