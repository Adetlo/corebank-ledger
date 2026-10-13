"""End-to-end smoke: seed, fund, transfer, fee, reverse, reconcile."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from tests.helpers import balance, create_account, fund, post_journal, transfer, trial_balance


def test_full_ledger_flow(client: TestClient) -> None:
    settlement = create_account(client, "Cash / Settlement GBP", "ASSET")
    customer_a = create_account(client, "Synthetic Customer A", "LIABILITY")
    customer_b = create_account(client, "Synthetic Customer B", "LIABILITY")
    fee_income = create_account(client, "Fee Income", "INCOME")

    fund(client, settlement["id"], customer_a["id"], "1000.00")
    assert balance(client, customer_a["id"]) == Decimal("1000.00")
    assert balance(client, settlement["id"]) == Decimal("1000.00")

    response = transfer(client, customer_a["id"], customer_b["id"], "250.00", reference="TRF-1")
    assert response.status_code == 201, response.text
    assert balance(client, customer_a["id"]) == Decimal("750.00")
    assert balance(client, customer_b["id"]) == Decimal("250.00")

    fee = post_journal(
        client,
        [(customer_a["id"], "DEBIT", "5.00"), (fee_income["id"], "CREDIT", "5.00")],
        reference="FEE-1",
    )
    assert fee.status_code == 201, fee.text
    assert balance(client, customer_a["id"]) == Decimal("745.00")
    assert balance(client, fee_income["id"]) == Decimal("5.00")

    tb = trial_balance(client)
    assert tb["balanced"] is True
    assert Decimal(tb["difference"]) == 0
    assert Decimal(tb["total_debits"]) == Decimal("1255.00")

    reverse = client.post(
        f"/api/v1/journal-entries/{fee.json()['id']}/reverse",
        json={"reason": "fee waived"},
        headers={"Idempotency-Key": "rev-1"},
    )
    assert reverse.status_code == 201, reverse.text
    assert reverse.json()["reversal_of"] == fee.json()["id"]
    assert balance(client, customer_a["id"]) == Decimal("750.00")
    assert balance(client, fee_income["id"]) == Decimal("0.00")

    original = client.get(f"/api/v1/journal-entries/{fee.json()['id']}").json()
    assert original["status"] == "REVERSED"
    assert original["reversed_by"] == reverse.json()["id"]

    tb = trial_balance(client)
    assert tb["balanced"] is True
    check = client.get("/api/v1/reconciliation/ledger-check").json()
    assert check["balanced"] is True
    assert check["unbalanced_journal_ids"] == []
