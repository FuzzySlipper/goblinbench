mod common;

use common::*;
use maintainability_mini_service::*;

#[test]
fn bulk_import_accepts_valid_rows_and_returns_summary() {
    let mut app = build_app();
    let response = post_bulk(
        &mut app,
        array(vec![
            customer_payload(
                "Ada Lovelace",
                "ada@example.com",
                Some("pro"),
                vec!["vip", "math"],
            ),
            customer_payload(
                "Grace Hopper",
                "GRACE@example.com",
                Some("enterprise"),
                vec![],
            ),
        ]),
        admin_user(),
    );

    assert_eq!(response.status_code, 200);
    assert_eq!(response.body.get("accepted_count"), Some(&number(2)));
    assert_eq!(response.body.get("rejected_count"), Some(&number(0)));
    let accepted = get_array(&response.body, "accepted");
    assert_eq!(
        get_string(get_object(&accepted[0]), "email"),
        "ada@example.com"
    );
    assert_eq!(
        get_string(get_object(&accepted[1]), "email"),
        "grace@example.com"
    );
    assert_eq!(get_array(&response.body, "rejected"), &[]);
    let emails: Vec<String> = app
        .repository
        .list_customers()
        .into_iter()
        .map(|c| c.email)
        .collect();
    assert_eq!(emails, vec!["ada@example.com", "grace@example.com"]);
    assert!(app.audit_log.list_events().is_empty());
}

#[test]
fn bulk_import_requires_bulk_permission_and_does_not_mutate_state() {
    let mut app = build_app();
    let response = post_bulk(
        &mut app,
        array(vec![customer_payload(
            "Ada",
            "ada@example.com",
            None,
            vec![],
        )]),
        User {
            id: "viewer".to_string(),
            role: "viewer".to_string(),
            permissions: Vec::new(),
        },
    );

    assert_eq!(response.status_code, 403);
    assert_eq!(response.body, map(vec![("error", text("forbidden"))]));
    assert!(app.repository.list_customers().is_empty());
    assert!(app.audit_log.list_events().is_empty());
}

#[test]
fn bulk_import_accepts_dedicated_permission_without_admin_role() {
    let mut app = build_app();
    let response = post_bulk(
        &mut app,
        array(vec![customer_payload(
            "Ada",
            "ada@example.com",
            None,
            vec![],
        )]),
        bulk_user(),
    );

    assert_eq!(response.status_code, 200);
    assert_eq!(response.body.get("accepted_count"), Some(&number(1)));
    assert!(app.repository.find_by_email("ada@example.com").is_some());
}

#[test]
fn bulk_import_rejects_invalid_rows_with_indexed_errors_and_audit_event() {
    let mut app = build_app();
    let response = post_bulk(
        &mut app,
        array(vec![
            object(vec![
                ("name", text("")),
                ("email", text("bad")),
                ("plan", text("gold")),
            ]),
            customer_payload(
                "Valid Customer",
                "valid@example.com",
                Some("free"),
                vec!["new"],
            ),
            object(vec![
                ("name", text("Bad Tags")),
                ("email", text("tags@example.com")),
                ("tags", array(vec![text("ok"), number(99)])),
            ]),
        ]),
        admin_user(),
    );

    assert_eq!(response.status_code, 200);
    assert_eq!(response.body.get("accepted_count"), Some(&number(1)));
    assert_eq!(response.body.get("rejected_count"), Some(&number(2)));
    let accepted = get_array(&response.body, "accepted");
    assert_eq!(
        get_string(get_object(&accepted[0]), "email"),
        "valid@example.com"
    );

    let rejected = get_array(&response.body, "rejected");
    let first = get_object(&rejected[0]);
    assert_eq!(first.get("index"), Some(&number(0)));
    let first_errors = get_array(first, "errors");
    assert_errors_contain(first_errors, "name is required");
    assert_errors_contain(first_errors, "email must be valid");
    assert_errors_contain(first_errors, "plan is invalid");

    assert_eq!(
        rejected[1],
        object(vec![
            ("index", number(2)),
            ("email", text("tags@example.com")),
            (
                "errors",
                array(vec![text("tags must be a list of strings")])
            )
        ])
    );

    let events = app.audit_log.list_events();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, "customers.bulk_import.rejected");
    assert_eq!(events[0].actor_id, "admin-1");
    assert_eq!(
        events[0].payload,
        map(vec![
            ("accepted_count", number(1)),
            ("rejected_count", number(2)),
        ])
    );
}

#[test]
fn bulk_import_rejects_existing_and_in_batch_duplicate_emails() {
    let mut app = build_app();
    app.handle(request(
        "POST",
        "/customers",
        get_object(&customer_payload(
            "Existing",
            "existing@example.com",
            None,
            vec![],
        ))
        .clone(),
        admin_user(),
    ));

    let response = post_bulk(
        &mut app,
        array(vec![
            customer_payload("Existing Again", "existing@example.com", None, vec![]),
            customer_payload("First", "dupe@example.com", None, vec![]),
            customer_payload("Second", "DUPE@example.com", None, vec![]),
        ]),
        admin_user(),
    );

    assert_eq!(response.status_code, 200);
    assert_eq!(response.body.get("accepted_count"), Some(&number(1)));
    let accepted = get_array(&response.body, "accepted");
    assert_eq!(
        get_string(get_object(&accepted[0]), "email"),
        "dupe@example.com"
    );
    assert_eq!(
        response.body.get("rejected"),
        Some(&array(vec![
            object(vec![
                ("index", number(0)),
                ("email", text("existing@example.com")),
                ("errors", array(vec![text("customer already exists")]))
            ]),
            object(vec![
                ("index", number(2)),
                ("email", text("dupe@example.com")),
                ("errors", array(vec![text("duplicate email in import")]))
            ]),
        ]))
    );
    let emails: Vec<String> = app
        .repository
        .list_customers()
        .into_iter()
        .map(|c| c.email)
        .collect();
    assert_eq!(emails, vec!["existing@example.com", "dupe@example.com"]);
}

#[test]
fn bulk_import_rejects_missing_or_non_list_rows_payload() {
    let mut app = build_app();
    let missing = app.handle(request(
        "POST",
        "/customers/bulk-import",
        map(vec![]),
        admin_user(),
    ));
    assert_eq!(missing.status_code, 400);
    assert_eq!(
        missing.body,
        map(vec![("error", text("rows must be a list"))])
    );

    let wrong_type = app.handle(request(
        "POST",
        "/customers/bulk-import",
        map(vec![("rows", text("not-list"))]),
        admin_user(),
    ));
    assert_eq!(wrong_type.status_code, 400);
    assert_eq!(
        wrong_type.body,
        map(vec![("error", text("rows must be a list"))])
    );
}

#[test]
fn bulk_import_preserves_existing_list_route_after_import() {
    let mut app = build_app();
    post_bulk(
        &mut app,
        array(vec![
            customer_payload("Ada", "ada@example.com", None, vec![]),
            customer_payload("Grace", "grace@example.com", None, vec![]),
        ]),
        admin_user(),
    );

    let listed = app.handle(request("GET", "/customers", map(vec![]), admin_user()));
    assert_eq!(listed.status_code, 200);
    let customers = get_array(&listed.body, "customers");
    assert_eq!(customers.len(), 2, "listed customers = {customers:?}");
    assert_eq!(
        get_string(get_object(&customers[0]), "email"),
        "ada@example.com"
    );
    assert_eq!(
        get_string(get_object(&customers[1]), "email"),
        "grace@example.com"
    );
}
