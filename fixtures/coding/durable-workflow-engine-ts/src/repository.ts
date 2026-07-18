import type { WorkflowRecord } from "./types";

export class InMemoryWorkflowRepository {
  private readonly workflows = new Map<string, WorkflowRecord>();
  private readonly idempotency = new Map<string, string>();
  private nextCreatedOrder = 0;
  private nextLeaseToken = 1;

  findByIdempotencyKey(key: string): WorkflowRecord | undefined {
    const id = this.idempotency.get(key);
    return id === undefined ? undefined : this.workflows.get(id);
  }

  get(id: string): WorkflowRecord | undefined {
    return this.workflows.get(id);
  }

  list(): WorkflowRecord[] {
    return [...this.workflows.values()];
  }

  insert(record: WorkflowRecord): void {
    this.workflows.set(record.definition.id, record);
    this.idempotency.set(record.idempotencyKey, record.definition.id);
  }

  allocateCreatedOrder(): number {
    return this.nextCreatedOrder++;
  }

  allocateLeaseToken(): number {
    return this.nextLeaseToken++;
  }
}
