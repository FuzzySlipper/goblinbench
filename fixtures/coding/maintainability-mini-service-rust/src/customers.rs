use crate::auth::can_write_customers;
use crate::models::{Customer, JsonValue, Request, Response, array, map, object, text};
use crate::router::Application;
use crate::validation::{normalize_customer_payload, validate_customer_payload};

/// Converts a customer model into an API response shape.
pub fn serialize_customer(customer: Customer) -> JsonValue {
    object(vec![
        ("id", text(&customer.id)),
        ("name", text(&customer.name)),
        ("email", text(&customer.email)),
        ("plan", text(&customer.plan)),
        (
            "tags",
            array(customer.tags.iter().map(|tag| text(tag)).collect()),
        ),
    ])
}

/// Lists all customers.
pub fn list_customers(_request: Request, app: &mut Application) -> Response {
    let customers = app
        .repository
        .list_customers()
        .into_iter()
        .map(serialize_customer)
        .collect();
    Response {
        status_code: 200,
        body: map(vec![("customers", array(customers))]),
    }
}

/// Creates a single customer through the existing endpoint.
pub fn create_customer(request: Request, app: &mut Application) -> Response {
    if !can_write_customers(request.user.as_ref()) {
        return Response {
            status_code: 403,
            body: map(vec![("error", text("forbidden"))]),
        };
    }

    let errors = validate_customer_payload(&request.json);
    if !errors.is_empty() {
        return Response {
            status_code: 400,
            body: map(vec![(
                "errors",
                array(errors.iter().map(|error| text(error)).collect()),
            )]),
        };
    }

    let normalized = normalize_customer_payload(&request.json);
    if app.repository.find_by_email(&normalized.email).is_some() {
        return Response {
            status_code: 409,
            body: map(vec![("error", text("customer already exists"))]),
        };
    }

    let customer = app.repository.create_customer(
        normalized.name,
        normalized.email,
        normalized.plan,
        normalized.tags,
    );
    Response {
        status_code: 201,
        body: map(vec![("customer", serialize_customer(customer))]),
    }
}

/// Imports many customers at once.
///
/// Implement this feature. The correct behavior crosses auth, validation,
/// repository, audit, and response-shaping concerns. Keep the existing single
/// customer endpoints working.
pub fn bulk_import_customers(_request: Request, _app: &mut Application) -> Response {
    Response {
        status_code: 501,
        body: map(vec![("error", text("bulk import not implemented"))]),
    }
}
