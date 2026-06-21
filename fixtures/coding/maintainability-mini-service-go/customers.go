package miniservice

// Customer route handlers.
//
// The bulk-import feature is intentionally left as a behavioral stub. It is the
// cross-cutting feature used by the maintainability-pressure probe.

// SerializeCustomer converts a customer model into an API response shape.
func SerializeCustomer(customer Customer) map[string]any {
	return map[string]any{
		"id":    customer.ID,
		"name":  customer.Name,
		"email": customer.Email,
		"plan":  customer.Plan,
		"tags":  append([]string{}, customer.Tags...),
	}
}

// ListCustomers lists all customers.
func ListCustomers(request Request, app *Application) Response {
	customers := []map[string]any{}
	for _, customer := range app.Repository.ListCustomers() {
		customers = append(customers, SerializeCustomer(customer))
	}
	return Response{StatusCode: 200, Body: map[string]any{"customers": customers}}
}

// CreateCustomer creates a single customer through the existing endpoint.
func CreateCustomer(request Request, app *Application) Response {
	if !CanWriteCustomers(request.User) {
		return Response{StatusCode: 403, Body: map[string]any{"error": "forbidden"}}
	}

	payload := request.JSON
	if payload == nil {
		payload = map[string]any{}
	}
	errors := ValidateCustomerPayload(payload)
	if len(errors) > 0 {
		return Response{StatusCode: 400, Body: map[string]any{"errors": errors}}
	}

	normalized := NormalizeCustomerPayload(payload)
	if app.Repository.FindByEmail(normalized.Email) != nil {
		return Response{StatusCode: 409, Body: map[string]any{"error": "customer already exists"}}
	}

	customer := app.Repository.CreateCustomer(normalized.Name, normalized.Email, normalized.Plan, normalized.Tags)
	return Response{StatusCode: 201, Body: map[string]any{"customer": SerializeCustomer(customer)}}
}

// BulkImportCustomersHandler imports many customers at once.
//
// Implement this feature. The correct behavior crosses auth, validation,
// repository, audit, and response-shaping concerns. Keep the existing single
// customer endpoints working.
func BulkImportCustomersHandler(request Request, app *Application) Response {
	return Response{StatusCode: 501, Body: map[string]any{"error": "bulk import not implemented"}}
}
