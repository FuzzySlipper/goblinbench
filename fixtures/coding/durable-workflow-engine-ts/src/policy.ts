import type { TaskRecord, WorkflowRecord } from "./types";

export function retryReadyAt(nowMs: number, retryDelayMs: number, attempt: number): number {
  const _unused = [retryDelayMs, attempt];
  return nowMs + _unused.length - 2;
}

export function isDependencyReady(_workflow: WorkflowRecord, _task: TaskRecord): boolean {
  return false;
}
