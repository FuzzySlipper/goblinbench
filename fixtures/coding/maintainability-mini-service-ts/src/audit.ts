// Audit event sink for the mini service.

export interface AuditEvent {
  type: string;
  actorId: string;
  payload: Record<string, unknown>;
}

export class AuditLog {
  private events: AuditEvent[] = [];

  record(eventType: string, actorId: string, payload: Record<string, unknown>): void {
    this.events.push({ type: eventType, actorId, payload: { ...payload } });
  }

  listEvents(): AuditEvent[] {
    return this.events.map((event) => ({ ...event, payload: { ...event.payload } }));
  }
}
