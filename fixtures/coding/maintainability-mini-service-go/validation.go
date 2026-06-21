package miniservice

import "strings"

var allowedPlans = map[string]struct{}{
	"free":       {},
	"pro":        {},
	"enterprise": {},
}

type NormalizedCustomerPayload struct {
	Name  string
	Email string
	Plan  string
	Tags  []string
}

// ValidateCustomerPayload validates the existing single-customer create payload.
func ValidateCustomerPayload(payload map[string]any) []string {
	errors := []string{}
	name, nameOK := payload["name"].(string)
	email, emailOK := payload["email"].(string)
	plan, planOK := payload["plan"].(string)
	if !planOK {
		plan = "free"
	}
	tags, tagsOK := payload["tags"].([]any)
	if _, exists := payload["tags"]; !exists {
		tagsOK = true
	}

	if !nameOK || strings.TrimSpace(name) == "" {
		errors = append(errors, "name is required")
	}
	if !emailOK || !isValidEmail(email) {
		errors = append(errors, "email must be valid")
	}
	if _, ok := allowedPlans[plan]; !ok {
		errors = append(errors, "plan is invalid")
	}
	if !tagsOK || !allStrings(tags) {
		errors = append(errors, "tags must be a list of strings")
	}

	return errors
}

// NormalizeCustomerPayload normalizes the existing single-customer create payload.
func NormalizeCustomerPayload(payload map[string]any) NormalizedCustomerPayload {
	plan, ok := payload["plan"].(string)
	if !ok {
		plan = "free"
	}
	return NormalizedCustomerPayload{
		Name:  strings.TrimSpace(asString(payload["name"])),
		Email: strings.ToLower(strings.TrimSpace(asString(payload["email"]))),
		Plan:  plan,
		Tags:  normalizeTags(payload["tags"]),
	}
}

func isValidEmail(email string) bool {
	at := strings.Index(email, "@")
	return at > 0 && strings.Contains(email[at+1:], ".")
}

func allStrings(values []any) bool {
	for _, value := range values {
		if _, ok := value.(string); !ok {
			return false
		}
	}
	return true
}

func normalizeTags(value any) []string {
	values, ok := value.([]any)
	if !ok {
		return []string{}
	}
	tags := make([]string, 0, len(values))
	for _, item := range values {
		tags = append(tags, strings.ToLower(strings.TrimSpace(asString(item))))
	}
	return tags
}

func asString(value any) string {
	text, _ := value.(string)
	return text
}
