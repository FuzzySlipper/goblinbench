from service.container import build_app
from service.models import Request, User


def admin() -> User:
    return User(id="admin-1", role="admin")


def test_existing_create_and_list_customer_flow_still_works():
    app = build_app()

    create = app.handle(
        Request(
            "POST",
            "/customers",
            json={"name": "Ada Lovelace", "email": "Ada@Example.COM", "plan": "pro", "tags": ["VIP"]},
            user=admin(),
        )
    )
    assert create.status_code == 201
    assert create.body["customer"]["email"] == "ada@example.com"
    assert create.body["customer"]["tags"] == ["vip"]

    listed = app.handle(Request("GET", "/customers", user=admin()))
    assert listed.status_code == 200
    assert [customer["email"] for customer in listed.body["customers"]] == ["ada@example.com"]


def test_existing_create_customer_rejects_invalid_payload():
    app = build_app()
    response = app.handle(Request("POST", "/customers", json={"name": "", "email": "bad", "plan": "gold"}, user=admin()))
    assert response.status_code == 400
    assert "name is required" in response.body["errors"]
    assert "email must be valid" in response.body["errors"]
    assert "plan is invalid" in response.body["errors"]


def test_existing_create_customer_requires_permission():
    app = build_app()
    response = app.handle(
        Request("POST", "/customers", json={"name": "Grace", "email": "grace@example.com"}, user=User(id="viewer"))
    )
    assert response.status_code == 403
    assert app.repository.list_customers() == []
