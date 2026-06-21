use crate::models::Customer;

/// Small repository with deterministic IDs for testability.
#[derive(Clone, Debug, Default)]
pub struct CustomerRepository {
    customers: Vec<Customer>,
    next_id: usize,
}

impl CustomerRepository {
    pub fn new() -> Self {
        Self {
            customers: Vec::new(),
            next_id: 1,
        }
    }

    pub fn list_customers(&self) -> Vec<Customer> {
        self.customers.clone()
    }

    pub fn find_by_email(&self, email: &str) -> Option<Customer> {
        let normalized = email.trim().to_lowercase();
        self.customers
            .iter()
            .find(|customer| customer.email == normalized)
            .cloned()
    }

    pub fn create_customer(
        &mut self,
        name: String,
        email: String,
        plan: String,
        tags: Vec<String>,
    ) -> Customer {
        let customer = Customer {
            id: format!("cus_{}", self.next_id),
            name,
            email: email.trim().to_lowercase(),
            plan,
            tags,
        };
        self.next_id += 1;
        self.customers.push(customer.clone());
        customer
    }
}
