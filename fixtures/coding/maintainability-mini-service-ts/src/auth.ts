// Authorization helpers for customer operations.

import type { User } from "./models";

export const WRITE_CUSTOMERS = "customers:write";
export const BULK_IMPORT_CUSTOMERS = "customers:bulk_import";

export function canWriteCustomers(user: User | undefined): boolean {
  return Boolean(user && (user.role === "admin" || user.permissions?.includes(WRITE_CUSTOMERS)));
}

export function canBulkImportCustomers(user: User | undefined): boolean {
  return Boolean(user && (user.role === "admin" || user.permissions?.includes(BULK_IMPORT_CUSTOMERS)));
}
