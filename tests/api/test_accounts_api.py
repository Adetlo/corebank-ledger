from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import create_account, fund, post_journal


def test_create_account_returns_201_with_synthetic_number(client: TestClient) -> None:
    response = client.post(
        "/api/v1/accounts",
        json={
            "account_name": "Synthetic Customer Current Account",
            "account_type": "LIABILITY",
            "currency": "GBP",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["account_number"].startswith("SYN-")
    assert body["normal_balance"] == "CREDIT"
    assert body["status"] == "ACTIVE"
    assert body["allow_negative_balance"] is False
    assert body["version"] == 1
    assert response.headers["X-Correlation-ID"]


def test_create_account_validation_errors(client: TestClient) -> None:
    response = client.post(
        "/api/v1/accounts",
        json={"account_name": "x", "account_type": "LIABILITY", "currency": "XXX"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_CURRENCY"
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]

    response = client.post(
        "/api/v1/accounts", json={"account_name": "", "account_type": "BOGUS", "currency": "GBP"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    locs = [e["loc"] for e in response.json()["error"]["details"]["errors"]]
    assert ["body", "account_type"] in locs

    response = client.post(
        "/api/v1/accounts",
        json={"account_name": "x", "account_type": "ASSET", "currency": "GBP", "extra": 1},
    )
    assert response.status_code == 422  # extra fields are forbidden


def test_get_account_and_not_found(client: TestClient) -> None:
    created = create_account(client, "A", "ASSET")
    assert client.get(f"/api/v1/accounts/{created['id']}").json()["id"] == created["id"]
    response = client.get(f"/api/v1/accounts/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert client.get("/api/v1/accounts/not-a-uuid").status_code == 422


def test_list_accounts_pagination_and_filters(client: TestClient) -> None:
    for i in range(5):
        create_account(client, f"L{i}", "LIABILITY")
    create_account(client, "USD asset", "ASSET", currency="USD")
    page = client.get("/api/v1/accounts", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 6 and len(page["items"]) == 2 and page["limit"] == 2
    page = client.get("/api/v1/accounts", params={"limit": 2, "offset": 4}).json()
    assert len(page["items"]) == 2
    page = client.get("/api/v1/accounts", params={"account_type": "ASSET"}).json()
    assert page["total"] == 1 and page["items"][0]["currency"] == "USD"
    page = client.get("/api/v1/accounts", params={"currency": "USD"}).json()
    assert page["total"] == 1
    assert client.get("/api/v1/accounts", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/accounts", params={"limit": 999}).status_code == 422


def test_balance_endpoint(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    customer = create_account(client, "C", "LIABILITY")
    fund(client, settlement["id"], customer["id"], "100.00")
    body = client.get(f"/api/v1/accounts/{customer['id']}/balance").json()
    assert body == {
        "account_id": customer["id"],
        "currency": "GBP",
        "normal_balance": "CREDIT",
        "debit_total": "0.00",
        "credit_total": "100.00",
        "balance": "100.00",
        "as_of_date": None,
        "posting_count": 1,
    }
    body = client.get(
        f"/api/v1/accounts/{customer['id']}/balance", params={"as_of_date": "2020-01-01"}
    ).json()
    assert body["balance"] == "0.00" and body["as_of_date"] == "2020-01-01"


def test_status_changes(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    customer = create_account(client, "C", "LIABILITY")
    fund(client, settlement["id"], customer["id"], "10.00")
    response = client.post(f"/api/v1/accounts/{customer['id']}/status", json={"status": "CLOSED"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "ACCOUNT_NOT_EMPTY"
    response = client.post(f"/api/v1/accounts/{customer['id']}/status", json={"status": "FROZEN"})
    assert response.status_code == 200 and response.json()["status"] == "FROZEN"
    blocked = post_journal(
        client, [(customer["id"], "DEBIT", "1.00"), (settlement["id"], "CREDIT", "1.00")]
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "ACCOUNT_FROZEN"
    assert (
        client.post(f"/api/v1/accounts/{uuid4()}/status", json={"status": "FROZEN"}).status_code
        == 404
    )
