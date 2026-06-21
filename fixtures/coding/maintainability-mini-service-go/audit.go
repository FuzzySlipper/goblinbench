package miniservice

type AuditEvent struct {
	Type    string
	ActorID string
	Payload map[string]any
}

// AuditLog is a tiny in-memory audit log used by tests and metrics fixtures.
type AuditLog struct {
	events []AuditEvent
}

func NewAuditLog() *AuditLog {
	return &AuditLog{}
}

func (a *AuditLog) Record(eventType string, actorID string, payload map[string]any) {
	a.events = append(a.events, AuditEvent{Type: eventType, ActorID: actorID, Payload: cloneMap(payload)})
}

func (a *AuditLog) ListEvents() []AuditEvent {
	events := make([]AuditEvent, len(a.events))
	for index, event := range a.events {
		events[index] = AuditEvent{Type: event.Type, ActorID: event.ActorID, Payload: cloneMap(event.Payload)}
	}
	return events
}

func cloneMap(input map[string]any) map[string]any {
	output := map[string]any{}
	for key, value := range input {
		output[key] = value
	}
	return output
}
