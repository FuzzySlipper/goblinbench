package miniservice

import "strings"

type Handler func(Request, *Application) Response

// Application is a minimal route dispatcher with shared repository/audit dependencies.
type Application struct {
	Repository *CustomerRepository
	AuditLog   *AuditLog
	routes     map[string]Handler
}

func NewApplication(repository *CustomerRepository, auditLog *AuditLog) *Application {
	return &Application{Repository: repository, AuditLog: auditLog, routes: map[string]Handler{}}
}

func (a *Application) AddRoute(method string, path string, handler Handler) {
	a.routes[strings.ToUpper(method)+" "+path] = handler
}

func (a *Application) Handle(request Request) Response {
	handler, ok := a.routes[strings.ToUpper(request.Method)+" "+request.Path]
	if !ok {
		return Response{StatusCode: 404, Body: map[string]any{"error": "not found"}}
	}
	return handler(request, a)
}
