import { EventOutbox } from "./outbox";
import { InMemoryWorkflowRepository } from "./repository";
import type { SubmitResult, TaskLease, WorkflowDefinition, WorkflowSnapshot } from "./types";

export class WorkflowEngine {
  constructor(
    public readonly repository = new InMemoryWorkflowRepository(),
    public readonly outbox = new EventOutbox(),
  ) {}

  submit(_definition: WorkflowDefinition, _idempotencyKey: string): SubmitResult {
    throw new Error("not implemented");
  }

  claim(_worker: string, _resources: string[], _nowMs: number, _leaseMs: number): TaskLease | undefined {
    return undefined;
  }

  heartbeat(_lease: TaskLease, _nowMs: number, _leaseMs: number): TaskLease {
    throw new Error("not implemented");
  }

  complete(_lease: TaskLease): void {
    throw new Error("not implemented");
  }

  fail(_lease: TaskLease, _nowMs: number, _retryable: boolean, _reason: string): void {
    throw new Error("not implemented");
  }

  cancelWorkflow(_workflowId: string): void {
    throw new Error("not implemented");
  }

  snapshot(_workflowId: string): WorkflowSnapshot {
    throw new Error("not implemented");
  }
}
