package miniservice

import (
	"reflect"
	"testing"
)

func bulkUser() *User {
	return &User{ID: "ops-1", Permissions: []string{"customers:bulk_import"}}
}

func postBulk(app *Application, rows any, user *User) Response {
	if user == nil {
		user = adminUser()
	}
	return app.Handle(Request{Method: "POST", Path: "/customers/bulk-import", JSON: map[string]any{"rows": rows}, User: user})
}

func TestBulkImportAcceptsValidRowsAndReturnsSummary(t *testing.T) {
	app := BuildApp()
	response := postBulk(app, []any{
		map[string]any{"name": "Ada Lovelace", "email": "ada@example.com", "plan": "pro", "tags": []any{"vip", "math"}},
		map[string]any{"name": "Grace Hopper", "email": "GRACE@example.com", "plan": "enterprise"},
	}, nil)

	if response.StatusCode != 200 {
		t.Fatalf("status = %d, want 200", response.StatusCode)
	}
	if response.Body["accepted_count"] != 2 || response.Body["rejected_count"] != 0 {
		t.Fatalf("counts = %#v", response.Body)
	}
	accepted := response.Body["accepted"].([]map[string]any)
	if got := []any{accepted[0]["email"], accepted[1]["email"]}; !reflect.DeepEqual(got, []any{"ada@example.com", "grace@example.com"}) {
		t.Fatalf("accepted emails = %#v", got)
	}
	if !reflect.DeepEqual(response.Body["rejected"], []map[string]any{}) {
		t.Fatalf("rejected = %#v", response.Body["rejected"])
	}
	if got := customerEmails(app.Repository.ListCustomers()); !reflect.DeepEqual(got, []string{"ada@example.com", "grace@example.com"}) {
		t.Fatalf("repository emails = %#v", got)
	}
	if len(app.AuditLog.ListEvents()) != 0 {
		t.Fatalf("unexpected audit events")
	}
}

func TestBulkImportRequiresBulkPermissionAndDoesNotMutateState(t *testing.T) {
	app := BuildApp()
	response := postBulk(app, []any{map[string]any{"name": "Ada", "email": "ada@example.com"}}, &User{ID: "viewer"})
	if response.StatusCode != 403 {
		t.Fatalf("status = %d, want 403", response.StatusCode)
	}
	if !reflect.DeepEqual(response.Body, map[string]any{"error": "forbidden"}) {
		t.Fatalf("body = %#v", response.Body)
	}
	if len(app.Repository.ListCustomers()) != 0 || len(app.AuditLog.ListEvents()) != 0 {
		t.Fatalf("state mutated")
	}
}

func TestBulkImportAcceptsDedicatedPermissionWithoutAdminRole(t *testing.T) {
	app := BuildApp()
	response := postBulk(app, []any{map[string]any{"name": "Ada", "email": "ada@example.com"}}, bulkUser())
	if response.StatusCode != 200 {
		t.Fatalf("status = %d, want 200", response.StatusCode)
	}
	if response.Body["accepted_count"] != 1 {
		t.Fatalf("accepted_count = %#v", response.Body["accepted_count"])
	}
	if app.Repository.FindByEmail("ada@example.com") == nil {
		t.Fatalf("customer not inserted")
	}
}

func TestBulkImportRejectsInvalidRowsWithIndexedErrorsAndAuditEvent(t *testing.T) {
	app := BuildApp()
	response := postBulk(app, []any{
		map[string]any{"name": "", "email": "bad", "plan": "gold"},
		map[string]any{"name": "Valid Customer", "email": "valid@example.com", "plan": "free", "tags": []any{"new"}},
		map[string]any{"name": "Bad Tags", "email": "tags@example.com", "tags": []any{"ok", 99}},
	}, nil)
	if response.StatusCode != 200 {
		t.Fatalf("status = %d, want 200", response.StatusCode)
	}
	if response.Body["accepted_count"] != 1 || response.Body["rejected_count"] != 2 {
		t.Fatalf("counts = %#v", response.Body)
	}
	accepted := response.Body["accepted"].([]map[string]any)
	if accepted[0]["email"] != "valid@example.com" {
		t.Fatalf("accepted = %#v", accepted)
	}
	rejected := response.Body["rejected"].([]map[string]any)
	if rejected[0]["index"] != 0 {
		t.Fatalf("first rejected index = %#v", rejected[0])
	}
	firstErrors := rejected[0]["errors"].([]string)
	assertContains(t, firstErrors, "name is required")
	assertContains(t, firstErrors, "email must be valid")
	assertContains(t, firstErrors, "plan is invalid")
	wantSecond := map[string]any{"index": 2, "email": "tags@example.com", "errors": []string{"tags must be a list of strings"}}
	if !reflect.DeepEqual(rejected[1], wantSecond) {
		t.Fatalf("second rejected = %#v", rejected[1])
	}

	events := app.AuditLog.ListEvents()
	if len(events) != 1 {
		t.Fatalf("events = %#v", events)
	}
	if events[0].Type != "customers.bulk_import.rejected" || events[0].ActorID != "admin-1" {
		t.Fatalf("event = %#v", events[0])
	}
	if !reflect.DeepEqual(events[0].Payload, map[string]any{"accepted_count": 1, "rejected_count": 2}) {
		t.Fatalf("payload = %#v", events[0].Payload)
	}
}

func TestBulkImportRejectsExistingAndInBatchDuplicateEmails(t *testing.T) {
	app := BuildApp()
	app.Handle(Request{Method: "POST", Path: "/customers", JSON: map[string]any{"name": "Existing", "email": "existing@example.com"}, User: adminUser()})
	response := postBulk(app, []any{
		map[string]any{"name": "Existing Again", "email": "existing@example.com"},
		map[string]any{"name": "First", "email": "dupe@example.com"},
		map[string]any{"name": "Second", "email": "DUPE@example.com"},
	}, nil)
	if response.StatusCode != 200 {
		t.Fatalf("status = %d, want 200", response.StatusCode)
	}
	accepted := response.Body["accepted"].([]map[string]any)
	if response.Body["accepted_count"] != 1 || accepted[0]["email"] != "dupe@example.com" {
		t.Fatalf("accepted = %#v", response.Body)
	}
	wantRejected := []map[string]any{
		{"index": 0, "email": "existing@example.com", "errors": []string{"customer already exists"}},
		{"index": 2, "email": "dupe@example.com", "errors": []string{"duplicate email in import"}},
	}
	if !reflect.DeepEqual(response.Body["rejected"], wantRejected) {
		t.Fatalf("rejected = %#v", response.Body["rejected"])
	}
	if got := customerEmails(app.Repository.ListCustomers()); !reflect.DeepEqual(got, []string{"existing@example.com", "dupe@example.com"}) {
		t.Fatalf("repository emails = %#v", got)
	}
}

func TestBulkImportRejectsMissingOrNonListRowsPayload(t *testing.T) {
	app := BuildApp()
	missing := app.Handle(Request{Method: "POST", Path: "/customers/bulk-import", JSON: map[string]any{}, User: adminUser()})
	if missing.StatusCode != 400 || !reflect.DeepEqual(missing.Body, map[string]any{"error": "rows must be a list"}) {
		t.Fatalf("missing = %#v", missing)
	}
	wrongType := app.Handle(Request{Method: "POST", Path: "/customers/bulk-import", JSON: map[string]any{"rows": "not-list"}, User: adminUser()})
	if wrongType.StatusCode != 400 || !reflect.DeepEqual(wrongType.Body, map[string]any{"error": "rows must be a list"}) {
		t.Fatalf("wrong type = %#v", wrongType)
	}
}

func TestBulkImportPreservesExistingListRouteAfterImport(t *testing.T) {
	app := BuildApp()
	postBulk(app, []any{map[string]any{"name": "Ada", "email": "ada@example.com"}, map[string]any{"name": "Grace", "email": "grace@example.com"}}, nil)
	listed := app.Handle(Request{Method: "GET", Path: "/customers", User: adminUser()})
	if listed.StatusCode != 200 {
		t.Fatalf("status = %d, want 200", listed.StatusCode)
	}
	customers := listed.Body["customers"].([]map[string]any)
	if len(customers) != 2 {
		t.Fatalf("listed customers = %#v", customers)
	}
	if got := []any{customers[0]["email"], customers[1]["email"]}; !reflect.DeepEqual(got, []any{"ada@example.com", "grace@example.com"}) {
		t.Fatalf("listed = %#v", got)
	}
}

func assertContains(t *testing.T, values []string, want string) {
	t.Helper()
	for _, value := range values {
		if value == want {
			return
		}
	}
	t.Fatalf("%q not found in %#v", want, values)
}

func customerEmails(customers []Customer) []string {
	emails := make([]string, 0, len(customers))
	for _, customer := range customers {
		emails = append(emails, customer.Email)
	}
	return emails
}
