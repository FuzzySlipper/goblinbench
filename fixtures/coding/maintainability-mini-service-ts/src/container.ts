// Application setup and dependency wiring.

import { AuditLog } from "./audit";
import { bulkImportCustomers, createCustomer, listCustomers } from "./handlers/customers";
import { CustomerRepository } from "./repository";
import { Application } from "./router";

export function buildApp(): Application {
  const app = new Application(new CustomerRepository(), new AuditLog());
  app.addRoute("GET", "/customers", listCustomers);
  app.addRoute("POST", "/customers", createCustomer);
  app.addRoute("POST", "/customers/bulk-import", bulkImportCustomers);
  return app;
}
