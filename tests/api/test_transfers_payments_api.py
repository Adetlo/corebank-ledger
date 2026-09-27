from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import balance, create_account, fund, transfer


def test_transfer_success_and_get(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    a = create_account(client, "A", "LIABILITY")
    b = create_account(client, "B", "LIABILITY")
    fund(client, settlement["id"], a["id"], "1000.00")
    response = transfer(
        client, a["id"], b["id"], "250.00", reference="TRF-DEMO-0001", idempotency_key="trf-1"
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == "250.00" and body["status"] == "POSTED"
    assert body["source_account_id"] == a["id"] and body["destination_account_id"] == b["id"]
    assert body["journal_entry"]["metadata"]["kind"] == "TRANSFER"
    assert body["transfer_id"] == body["journal_entry"]["id"]
    assert balance(client, a["id"]) == 750 and balance(client, b["id"]) == 250
    assert (
        client.get(f"/api/v1/transfers/{body['transfer_id']}").json()["reference"]
        == "TRF-DEMO-0001"
    )
    assert client.get(f"/api/v1/transfers/{uuid4()}").status_code == 404

    replay = transfer(
        client, a["id"], b["id"], "250.00", reference="TRF-DEMO-0001", idempotency_key="trf-1"
    )
    assert replay.status_code == 200 and replay.json()["transfer_id"] == body["transfer_id"]
    assert balance(client, a["id"]) == 750


def test_transfer_errors(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    a = create_account(client, "A", "LIABILITY")
    b = create_account(client, "B", "LIABILITY")
    fund(client, settlement["id"], a["id"], "100.00")
    r = transfer(client, a["id"], b["id"], "100.01")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_FUNDS"
    r = transfer(client, settlement["id"], a["id"], "1.00")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TRANSFER"
    r = transfer(client, a["id"], a["id"], "1.00")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TRANSFER"
    r = transfer(client, a["id"], b["id"], "1.00", currency="USD")
    assert r.status_code == 422 and r.json()["error"]["code"] == "CURRENCY_MISMATCH"
    r = transfer(client, a["id"], str(uuid4()), "1.00")
    assert r.status_code == 404
    r = client.post(
        "/api/v1/transfers",
        json={
            "source_account_id": a["id"],
            "destination_account_id": b["id"],
            "amount": "1.00",
            "currency": "GBP",
            "reference": "X",
        },
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"
    r = transfer(client, a["id"], b["id"], "0.00")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AMOUNT"


def test_payment_instruction_adapter(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    a = create_account(client, "A", "LIABILITY")
    b = create_account(client, "B", "LIABILITY")
    fund(client, settlement["id"], a["id"], "100.00")
    instruction = {
        "payment_id": "PMT-2026-000123",
        "end_to_end_id": "E2E-INV-55821",
        "debtor_account": a["id"],
        "creditor_account": b["id"],
        "amount": "12.50",
        "currency": "GBP",
        "requested_execution_date": "2026-10-14",
        "remittance_information": "Invoice 55821",
    }
    r = client.post(
        "/api/v1/payments/instructions", json=instruction, headers={"Idempotency-Key": "pmt-1"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["reference"] == "E2E-INV-55821" and body["value_date"] == "2026-10-14"
    assert (
        body["journal_entry"]["metadata"]["source_model"] == "ISO 20022-inspired simplified model"
    )
    assert balance(client, b["id"]) == 12.5
    r = client.post(
        "/api/v1/payments/instructions", json=instruction, headers={"Idempotency-Key": "pmt-1"}
    )
    assert r.status_code == 200 and r.headers["Idempotent-Replayed"] == "true"
    assert balance(client, b["id"]) == 12.5
