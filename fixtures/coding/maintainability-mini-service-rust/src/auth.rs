use crate::models::User;

pub const WRITE_CUSTOMERS: &str = "customers:write";
pub const BULK_IMPORT_CUSTOMERS: &str = "customers:bulk_import";

/// Reports whether a user can create individual customers.
pub fn can_write_customers(user: Option<&User>) -> bool {
    user.is_some_and(|user| user.role == "admin" || has_permission(user, WRITE_CUSTOMERS))
}

/// Reports whether a user can bulk-import customers.
pub fn can_bulk_import_customers(user: Option<&User>) -> bool {
    user.is_some_and(|user| user.role == "admin" || has_permission(user, BULK_IMPORT_CUSTOMERS))
}

fn has_permission(user: &User, permission: &str) -> bool {
    user.permissions
        .iter()
        .any(|existing| existing == permission)
}
