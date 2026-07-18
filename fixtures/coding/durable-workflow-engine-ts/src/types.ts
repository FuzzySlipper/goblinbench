export interface TaskSpec {
  id: string;
  dependencies: string[];
  resource: string;
  maxAttempts: number;
  retryDelayMs: number;
}

export interface WorkflowDefinition {
  id: string;
  tasks: TaskSpec[];
}

export type TaskStatus =
  | "pending"
  | "leased"
  | "retry_wait"
  | "succeeded"
  | "failed"
  | "blocked"
  | "cancelled";

export interface TaskRecord {
  spec: TaskSpec;
  status: TaskStatus;
  attempts: number;
  lease?: { worker: string; token: number; expiresAtMs: number };
  readyAtMs?: number;
  failure?: string;
  blockedBy?: string;
}

export type WorkflowStatus = "running" | "succeeded" | "failed" | "cancelled";

export interface WorkflowRecord {
  definition: WorkflowDefinition;
  idempotencyKey: string;
  createdOrder: number;
  revision: number;
  status: WorkflowStatus;
  tasks: Map<string, TaskRecord>;
}

export interface TaskLease {
  workflowId: string;
  taskId: string;
  worker: string;
  token: number;
  attempt: number;
  expiresAtMs: number;
}

export interface WorkflowSnapshot {
  id: string;
  revision: number;
  status: WorkflowStatus;
  tasks: Record<string, {
    status: TaskStatus;
    attempts: number;
    readyAtMs?: number;
    failure?: string;
    blockedBy?: string;
  }>;
}

export interface WorkflowEvent {
  sequence: number;
  type: string;
  workflowId: string;
  taskId?: string;
  detail: Record<string, unknown>;
}

export type SubmitResult = { workflowId: string; replayed: boolean };

export class WorkflowError extends Error {
  constructor(
    public readonly code:
      | "invalid_definition"
      | "idempotency_conflict"
      | "unknown_workflow"
      | "stale_lease"
      | "invalid_transition",
    message: string,
  ) {
    super(message);
  }
}
