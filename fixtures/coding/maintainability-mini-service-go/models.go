package miniservice

// Fixed request/response and domain model types for the mini service.
type User struct {
	ID          string
	Role        string
	Permissions []string
}

type Request struct {
	Method string
	Path   string
	JSON   map[string]any
	User   *User
}

type Response struct {
	StatusCode int
	Body       map[string]any
}

type Customer struct {
	ID    string
	Name  string
	Email string
	Plan  string
	Tags  []string
}
