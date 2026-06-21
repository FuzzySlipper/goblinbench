package miniservice

// BuildApp builds the mini application and registers routes.
func BuildApp() *Application {
	app := NewApplication(NewCustomerRepository(), NewAuditLog())
	app.AddRoute("GET", "/customers", ListCustomers)
	app.AddRoute("POST", "/customers", CreateCustomer)
	app.AddRoute("POST", "/customers/bulk-import", BulkImportCustomersHandler)
	return app
}
