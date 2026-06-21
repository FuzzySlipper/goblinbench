// In-memory customer repository used by the fixture tests.

import type { Customer, Plan } from "./models";

export class CustomerRepository {
  private customers: Customer[] = [];
  private nextId = 1;

  listCustomers(): Customer[] {
    return [...this.customers];
  }

  findByEmail(email: string): Customer | undefined {
    const normalized = email.trim().toLowerCase();
    return this.customers.find((customer) => customer.email === normalized);
  }

  createCustomer(name: string, email: string, plan: Plan, tags: readonly string[] = []): Customer {
    const customer: Customer = {
      id: `cus_${this.nextId}`,
      name,
      email: email.trim().toLowerCase(),
      plan,
      tags: [...tags],
    };
    this.nextId += 1;
    this.customers.push(customer);
    return customer;
  }
}
