mod common;

use common::*;
use maintainability_mini_service::*;

#[test]
fn existing_create_and_list_customer_flow_still_works() {
    let mut app = build_app();
    let create = app.handle(request(
        "POST",
        "/customers",
        get_object(&customer_payload(
            "Ada Lovelace",
            "Ada@Example.COM",
            Some("pro"),
            vec!["VIP"],
        ))
        .clone(),
        admin_user(),
    ));

    assert_eq!(create.status_code, 201);
    let customer = get_object(create.body.get("customer").unwrap());
    assert_eq!(get_string(customer, "email"), "ada@example.com");
    assert_eq!(customer.get("tags"), Some(&array(vec![text("vip")])));

    let listed = app.handle(request("GET", "/customers", map(vec![]), admin_user()));
    assert_eq!(listed.status_code, 200);
    let customers = get_array(&listed.body, "customers");
    let listed_customer = get_object(&customers[0]);
    assert_eq!(get_string(listed_customer, "email"), "ada@example.com");
}

#[test]
fn existing_create_customer_rejects_invalid_payload() {
    let mut app = build_app();
    let response = app.handle(request(
        "POST",
        "/customers",
        map(vec![
            ("name", text("")),
            ("email", text("bad")),
            ("plan", text("gold")),
        ]),
        admin_user(),
    ));

    assert_eq!(response.status_code, 400);
    let errors = get_array(&response.body, "errors");
    assert_errors_contain(errors, "name is required");
    assert_errors_contain(errors, "email must be valid");
    assert_errors_contain(errors, "plan is invalid");
}

#[test]
fn existing_create_customer_requires_permission() {
    let mut app = build_app();
    let response = app.handle(request(
        "POST",
        "/customers",
        get_object(&customer_payload(
            "Grace",
            "grace@example.com",
            None,
            vec![],
        ))
        .clone(),
        User {
            id: "viewer".to_string(),
            role: "viewer".to_string(),
            permissions: Vec::new(),
        },
    ));

    assert_eq!(response.status_code, 403);
    assert!(app.repository.list_customers().is_empty());
}
