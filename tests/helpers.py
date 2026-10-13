"""Small helpers shared by integration and API tests."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

TODAY = date(2026, 10, 13)


def key() -> str:
    return f"test-{uuid.uuid4()}"


def create_account(
    client: TestClient,
    name: str,
    account_type: str,
    currency: str = "GBP",
    allow_negative_balance: bool | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "account_name": name,
        "account_type": account_type,
        "currency": currency,
    }
    if allow_negative_balance is not None:
        body["allow_negative_balance"] = allow_negative_balance
    response = client.post("/api/v1/accounts", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def post_journal(
    client: TestClient,
    postings: list[tuple[str, str, str]],
    *,
    reference: str = "JRN-TEST",
    currency: str = "GBP",
    idempotency_key: str | None = None,
    booking_date: date = TODAY,
    description: str = "test entry",
) -> Any:
    body = {
        "reference": reference,
        "description": description,
        "booking_date": booking_date.isoformat(),
        "postings": [
            {
                "account_id": account_id,
                "direction": direction,
                "amount": amount,
                "currency": currency,
            }
            for account_id, direction, amount in postings
        ],
    }
    headers = {"Idempotency-Key": idempotency_key or key()}
    return client.post("/api/v1/journal-entries", json=body, headers=headers)


def fund(
    client: TestClient, asset_id: str, liability_id: str, amount: str, currency: str = "GBP"
) -> dict[str, Any]:
    response = post_journal(
        client,
        [(asset_id, "DEBIT", amount), (liability_id, "CREDIT", amount)],
        reference=f"FUND-{uuid.uuid4().hex[:8]}",
        currency=currency,
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def balance(client: TestClient, account_id: str, as_of_date: date | None = None) -> Decimal:
    params = {"as_of_date": as_of_date.isoformat()} if as_of_date else None
    response = client.get(f"/api/v1/accounts/{account_id}/balance", params=params)
    assert response.status_code == 200, response.text
    return Decimal(response.json()["balance"])


def transfer(
    client: TestClient,
    source: str,
    destination: str,
    amount: str,
    *,
    currency: str = "GBP",
    reference: str = "TRF-TEST",
    idempotency_key: str | None = None,
) -> Any:
    body = {
        "source_account_id": source,
        "destination_account_id": destination,
        "amount": amount,
        "currency": currency,
        "reference": reference,
        "value_date": TODAY.isoformat(),
        "booking_date": TODAY.isoformat(),
    }
    return client.post(
        "/api/v1/transfers", json=body, headers={"Idempotency-Key": idempotency_key or key()}
    )


def trial_balance(client: TestClient, currency: str = "GBP") -> dict[str, Any]:
    response = client.get("/api/v1/reconciliation/trial-balance", params={"currency": currency})
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data
