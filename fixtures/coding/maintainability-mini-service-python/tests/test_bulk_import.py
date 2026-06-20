from service.container import build_app
from service.models import Request, User


def admin() -> User:
    return User(id="admin-1", role="admin")


def bulk_user() -> User:
    return User(id="ops-1", permissions=("customers:bulk_import",))


def post_bulk(app, rows, user=None):
    return app.handle(Request("POST", "/customers/bulk-import", json={"rows": rows}, user=user or admin()))


def test_bulk_import_accepts_valid_rows_and_returns_summary():
    app = build_app()
    response = post_bulk(
        app,
        [
            {"name": "Ada Lovelace", "email": "ada@example.com", "plan": "pro", "tags": ["vip", "math"]},
            {"name": "Grace Hopper", "email": "GRACE@example.com", "plan": "enterprise"},
        ],
    )

    assert response.status_code == 200
    assert response.body["accepted_count"] == 2
    assert response.body["rejected_count"] == 0
    assert [item["email"] for item in response.body["accepted"]] == ["ada@example.com", "grace@example.com"]
    assert response.body["rejected"] == []
    assert [customer.email for customer in app.repository.list_customers()] == ["ada@example.com", "grace@example.com"]
    assert app.audit_log.list_events() == []


def test_bulk_import_requires_bulk_permission_and_does_not_mutate_state():
    app = build_app()
    response = post_bulk(app, [{"name": "Ada", "email": "ada@example.com"}], user=User(id="viewer"))

    assert response.status_code == 403
    assert response.body == {"error": "forbidden"}
    assert app.repository.list_customers() == []
    assert app.audit_log.list_events() == []


def test_bulk_import_accepts_dedicated_permission_without_admin_role():
    app = build_app()
    response = post_bulk(app, [{"name": "Ada", "email": "ada@example.com"}], user=bulk_user())

    assert response.status_code == 200
    assert response.body["accepted_count"] == 1
    assert app.repository.find_by_email("ada@example.com") is not None


def test_bulk_import_rejects_invalid_rows_with_indexed_errors_and_audit_event():
    app = build_app()
    response = post_bulk(
        app,
        [
            {"name": "", "email": "bad", "plan": "gold"},
            {"name": "Valid Customer", "email": "valid@example.com", "plan": "free", "tags": ["new"]},
            {"name": "Bad Tags", "email": "tags@example.com", "tags": ["ok", 99]},
        ],
    )

    assert response.status_code == 200
    assert response.body["accepted_count"] == 1
    assert response.body["rejected_count"] == 2
    assert response.body["accepted"][0]["email"] == "valid@example.com"
    assert response.body["rejected"][0]["index"] == 0
    assert "name is required" in response.body["rejected"][0]["errors"]
    assert "email must be valid" in response.body["rejected"][0]["errors"]
    assert "plan is invalid" in response.body["rejected"][0]["errors"]
    assert response.body["rejected"][1] == {"index": 2, "email": "tags@example.com", "errors": ["tags must be a list of strings"]}

    events = app.audit_log.list_events()
    assert len(events) == 1
    assert events[0]["type"] == "customers.bulk_import.rejected"
    assert events[0]["actor_id"] == "admin-1"
    assert events[0]["payload"] == {"accepted_count": 1, "rejected_count": 2}


def test_bulk_import_rejects_existing_and_in_batch_duplicate_emails():
    app = build_app()
    app.handle(Request("POST", "/customers", json={"name": "Existing", "email": "existing@example.com"}, user=admin()))

    response = post_bulk(
        app,
        [
            {"name": "Existing Again", "email": "existing@example.com"},
            {"name": "First", "email": "dupe@example.com"},
            {"name": "Second", "email": "DUPE@example.com"},
        ],
    )

    assert response.status_code == 200
    assert response.body["accepted_count"] == 1
    assert response.body["accepted"][0]["email"] == "dupe@example.com"
    assert response.body["rejected"] == [
        {"index": 0, "email": "existing@example.com", "errors": ["customer already exists"]},
        {"index": 2, "email": "dupe@example.com", "errors": ["duplicate email in import"]},
    ]
    assert [customer.email for customer in app.repository.list_customers()] == ["existing@example.com", "dupe@example.com"]


def test_bulk_import_rejects_missing_or_non_list_rows_payload():
    app = build_app()

    missing = app.handle(Request("POST", "/customers/bulk-import", json={}, user=admin()))
    assert missing.status_code == 400
    assert missing.body == {"error": "rows must be a list"}

    wrong_type = app.handle(Request("POST", "/customers/bulk-import", json={"rows": "not-list"}, user=admin()))
    assert wrong_type.status_code == 400
    assert wrong_type.body == {"error": "rows must be a list"}


def test_bulk_import_preserves_existing_list_route_after_import():
    app = build_app()
    post_bulk(app, [{"name": "Ada", "email": "ada@example.com"}, {"name": "Grace", "email": "grace@example.com"}])

    listed = app.handle(Request("GET", "/customers", user=admin()))
    assert listed.status_code == 200
    assert [customer["email"] for customer in listed.body["customers"]] == ["ada@example.com", "grace@example.com"]
