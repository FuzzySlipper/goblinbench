package miniservice

import (
	"reflect"
	"testing"
)

func adminUser() *User {
	return &User{ID: "admin-1", Role: "admin"}
}

func TestExistingCreateAndListCustomerFlowStillWorks(t *testing.T) {
	app := BuildApp()

	create := app.Handle(Request{
		Method: "POST",
		Path:   "/customers",
		JSON: map[string]any{
			"name":  "Ada Lovelace",
			"email": "Ada@Example.COM",
			"plan":  "pro",
			"tags":  []any{"VIP"},
		},
		User: adminUser(),
	})
	if create.StatusCode != 201 {
		t.Fatalf("status = %d, want 201", create.StatusCode)
	}
	customer := create.Body["customer"].(map[string]any)
	if customer["email"] != "ada@example.com" {
		t.Fatalf("email = %v", customer["email"])
	}
	if !reflect.DeepEqual(customer["tags"], []string{"vip"}) {
		t.Fatalf("tags = %#v", customer["tags"])
	}

	listed := app.Handle(Request{Method: "GET", Path: "/customers", User: adminUser()})
	if listed.StatusCode != 200 {
		t.Fatalf("list status = %d", listed.StatusCode)
	}
	customers := listed.Body["customers"].([]map[string]any)
	if got := customers[0]["email"]; got != "ada@example.com" {
		t.Fatalf("listed email = %v", got)
	}
}

func TestExistingCreateCustomerRejectsInvalidPayload(t *testing.T) {
	app := BuildApp()
	response := app.Handle(Request{Method: "POST", Path: "/customers", JSON: map[string]any{"name": "", "email": "bad", "plan": "gold"}, User: adminUser()})
	if response.StatusCode != 400 {
		t.Fatalf("status = %d, want 400", response.StatusCode)
	}
	errors := response.Body["errors"].([]string)
	assertContains(t, errors, "name is required")
	assertContains(t, errors, "email must be valid")
	assertContains(t, errors, "plan is invalid")
}

func TestExistingCreateCustomerRequiresPermission(t *testing.T) {
	app := BuildApp()
	response := app.Handle(Request{Method: "POST", Path: "/customers", JSON: map[string]any{"name": "Grace", "email": "grace@example.com"}, User: &User{ID: "viewer"}})
	if response.StatusCode != 403 {
		t.Fatalf("status = %d, want 403", response.StatusCode)
	}
	if len(app.Repository.ListCustomers()) != 0 {
		t.Fatalf("repository mutated")
	}
}
