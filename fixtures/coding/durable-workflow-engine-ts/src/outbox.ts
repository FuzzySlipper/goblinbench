import type { WorkflowEvent } from "./types";

export class EventOutbox {
  private readonly events: WorkflowEvent[] = [];

  append(event: Omit<WorkflowEvent, "sequence">): WorkflowEvent {
    const stored: WorkflowEvent = { ...event, sequence: this.events.length + 1 };
    this.events.push(stored);
    return stored;
  }

  after(sequence: number): WorkflowEvent[] {
    return this.events.filter((event) => event.sequence > sequence).map((event) => ({ ...event, detail: { ...event.detail } }));
  }
}
