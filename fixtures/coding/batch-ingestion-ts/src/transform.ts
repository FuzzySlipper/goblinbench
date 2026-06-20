/** Record transformation — sign your implementation here.
 *
 * All function signatures are fixed. Fill the function bodies.
 */

import type { IngestRecord } from "./types";

export function normalizePayload(record: IngestRecord): IngestRecord {
  /**
   * Normalise payload keys to snake_case.
   *
   * For every key in payload:
   *   - Convert PascalCase/CamelCase keys to snake_case.
   *   - Trim whitespace from string values.
   *   - Leave non-string values unchanged.
   *
   * Return a new record with the transformed payload.
   * Do NOT mutate the input record.
   */
  throw new Error("not implemented");
}

export function flattenPayload(record: IngestRecord): IngestRecord {
  /**
   * Flatten one level of nested object values in payload.
   *
   * e.g. { user: { name: "alice", id: 7 } } becomes
   *      { user_name: "alice", user_id: 7, ...otherKeys }
   *
   * Only flatten one level. Non-plain-object values stay as-is.
   * Return a new record with the flattened payload.
   */
  throw new Error("not implemented");
}

export function transformBatch(records: IngestRecord[]): IngestRecord[] {
  /** Apply normalizePayload then flattenPayload to every record.
   *
   * Return new records in the original order.
   */
  throw new Error("not implemented");
}
