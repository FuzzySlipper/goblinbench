package miniservice

import "strings"

// CustomerRepository is a small repository with deterministic IDs for testability.
type CustomerRepository struct {
	customers []Customer
	nextID    int
}

func NewCustomerRepository() *CustomerRepository {
	return &CustomerRepository{nextID: 1}
}

func (r *CustomerRepository) ListCustomers() []Customer {
	customers := make([]Customer, len(r.customers))
	copy(customers, r.customers)
	return customers
}

func (r *CustomerRepository) FindByEmail(email string) *Customer {
	normalized := strings.ToLower(strings.TrimSpace(email))
	for index := range r.customers {
		if r.customers[index].Email == normalized {
			customer := r.customers[index]
			return &customer
		}
	}
	return nil
}

func (r *CustomerRepository) CreateCustomer(name string, email string, plan string, tags []string) Customer {
	customer := Customer{
		ID:    "cus_" + itoa(r.nextID),
		Name:  name,
		Email: strings.ToLower(strings.TrimSpace(email)),
		Plan:  plan,
		Tags:  append([]string{}, tags...),
	}
	r.nextID++
	r.customers = append(r.customers, customer)
	return customer
}

func itoa(value int) string {
	if value == 0 {
		return "0"
	}
	digits := []byte{}
	for value > 0 {
		digits = append([]byte{byte('0' + value%10)}, digits...)
		value /= 10
	}
	return string(digits)
}
