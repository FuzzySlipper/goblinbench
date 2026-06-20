/**
 * Data types for the batch ingestion pipeline.
 *
 * DO NOT MODIFY this file. It is the fixed interface for the probe.
 */

export type Payload = Record<string, unknown>;

export interface IngestRecord {
  readonly recordType: string;
  readonly ts: Date;
  readonly payload: Payload;
  readonly tags: ReadonlySet<string>;
}

export interface ValidationError {
  readonly field: string;
  readonly reason: string;
}

export interface TypeSummary {
  readonly recordType: string;
  readonly count: number;
  readonly firstTs?: Date;
  readonly lastTs?: Date;
  readonly avgPayloadKeys: number;
}

export interface BatchResult {
  readonly ingested: number;
  readonly rejected: number;
  readonly summaries: TypeSummary[];
}
