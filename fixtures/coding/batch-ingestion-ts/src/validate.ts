/** Record validation — sign your implementation here.
 *
 * All function signatures are fixed. Fill the function bodies.
 */

import type { IngestRecord, ValidationError } from "./types";

export function validateRecord(record: IngestRecord): ValidationError[] {
  /**
   * Check a single record against all validation rules.
   *
   * Rules:
   *   - recordType must be non-empty and alphanumeric.
   *   - ts must not be in the future (allow 1 s clock skew).
   *   - payload must be non-empty.
   *   - tags may be empty (no rule required).
   *
   * Return a list of errors (empty = valid).
   */
  throw new Error("not implemented");
}

export function validateBatch(
  records: IngestRecord[],
): [IngestRecord[], Array<[IngestRecord, ValidationError[]]>] {
  /**
   * Split records into [valid, invalidWithErrors].
   *
   * Invalid records are paired with their validation errors.
   * Order of valid records must match input order.
   */
  throw new Error("not implemented");
}
