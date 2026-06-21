package miniservice

const WriteCustomers = "customers:write"
const BulkImportCustomers = "customers:bulk_import"

// CanWriteCustomers reports whether a user can create individual customers.
func CanWriteCustomers(user *User) bool {
	return user != nil && (user.Role == "admin" || hasPermission(user, WriteCustomers))
}

// CanBulkImportCustomers reports whether a user can bulk-import customers.
func CanBulkImportCustomers(user *User) bool {
	return user != nil && (user.Role == "admin" || hasPermission(user, BulkImportCustomers))
}

func hasPermission(user *User, permission string) bool {
	for _, existing := range user.Permissions {
		if existing == permission {
			return true
		}
	}
	return false
}
