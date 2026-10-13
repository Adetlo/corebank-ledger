"""Runnable end-to-end demonstration against a live API.

Flow:
  1. seed accounts
  2. initial funding (debit settlement asset, credit customer liability)
  3. transfer GBP 250 from Customer A to Customer B
  4. charge a GBP 5 synthetic service fee
  5. query balances
  6. trial balance
  7. reverse the fee
  8. final trial balance (still balanced)
Plus: prove an unbalanced entry is rejected and an idempotent replay posts nothing twice.

Usage::

    docker compose up -d --build
    uv run python scripts/demo.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _client import LedgerClient
from seed_demo import seed


def banner(step: str) -> None:
    print(f"\n=== {step} ===")


def show_balances(client: LedgerClient, accounts: dict[str, dict[str, Any]]) -> None:
    for key in ("settlement", "customer_a", "customer_b", "fee_income"):
        account = accounts[key]
        bal = client.balance(account["id"])
        print(
            f"  {account['account_name']:<24} {bal['balance']:>12} {bal['currency']}"
            f"   (dr {bal['debit_total']}, cr {bal['credit_total']})"
        )


def show_trial_balance(client: LedgerClient) -> dict[str, Any]:
    tb = client.trial_balance("GBP")
    print(f"  {'account':<24} {'type':<9} {'debits':>12} {'credits':>12} {'net':>12}")
    for line in tb["accounts"]:
        print(
            f"  {line['account_name']:<24} {line['account_type']:<9} {line['debit_total']:>12} "
            f"{line['credit_total']:>12} {line['net_balance']:>12}"
        )
    print(f"  {'TOTAL':<34} {tb['total_debits']:>12} {tb['total_credits']:>12}")
    print(f"  difference={tb['difference']} balanced={tb['balanced']}")
    return tb


def main() -> None:
    client = LedgerClient()
    client.wait_ready()
    today = datetime.now(UTC).date().isoformat()
    run = uuid.uuid4().hex[:8]

    banner("1. Seed synthetic accounts")
    accounts = seed(client)
    settlement, a, b, fees = (
        accounts[k] for k in ("settlement", "customer_a", "customer_b", "fee_income")
    )

    banner("2. Initial funding: debit settlement asset / credit customer liability")
    funding = client.post_journal(
        reference=f"DEP-DEMO-{run}",
        description="Synthetic deposit for Customer A",
        booking_date=today,
        postings=[
            {
                "account_id": settlement["id"],
                "direction": "DEBIT",
                "amount": "1000.00",
                "currency": "GBP",
            },
            {"account_id": a["id"], "direction": "CREDIT", "amount": "1000.00", "currency": "GBP"},
        ],
    )
    print(f"  posted {funding['reference']} status={funding['status']} id={funding['id']}")

    banner("2b. Unbalanced entry is rejected (999.99 vs 1000.00)")
    bad = client.post_journal_raw(
        {
            "reference": f"BAD-{run}",
            "description": "should fail",
            "booking_date": today,
            "postings": [
                {
                    "account_id": settlement["id"],
                    "direction": "DEBIT",
                    "amount": "999.99",
                    "currency": "GBP",
                },
                {
                    "account_id": a["id"],
                    "direction": "CREDIT",
                    "amount": "1000.00",
                    "currency": "GBP",
                },
            ],
        },
        idempotency_key=f"bad-{run}",
    )
    print(
        f"  HTTP {bad.status_code} {bad.json()['error']['code']}: {bad.json()['error']['message']}"
    )
    assert bad.status_code == 422

    banner("3. Transfer GBP 250.00 from Customer A to Customer B")
    transfer_body = {
        "source_account_id": a["id"],
        "destination_account_id": b["id"],
        "amount": "250.00",
        "currency": "GBP",
        "reference": f"TRF-DEMO-{run}",
        "value_date": today,
    }
    transfer_key = f"trf-{run}"
    first = client.transfer(transfer_body, transfer_key)
    print(f"  HTTP {first.status_code} transfer_id={first.json()['transfer_id']}")
    assert first.status_code == 201

    banner("3b. Idempotent replay of the same transfer (same key, same payload)")
    replay = client.transfer(transfer_body, transfer_key)
    print(
        f"  HTTP {replay.status_code} Idempotent-Replayed={replay.headers.get('Idempotent-Replayed')} "
        f"same transfer_id={replay.json()['transfer_id'] == first.json()['transfer_id']}"
    )
    assert replay.status_code == 200 and replay.json()["transfer_id"] == first.json()["transfer_id"]
    conflict = client.transfer({**transfer_body, "amount": "251.00"}, transfer_key)
    print(
        f"  HTTP {conflict.status_code} {conflict.json()['error']['code']} for same key + different payload"
    )
    assert conflict.status_code == 409

    banner("4. Charge GBP 5.00 synthetic service fee to Customer A")
    fee = client.post_journal(
        reference=f"FEE-DEMO-{run}",
        description="Synthetic monthly service fee",
        booking_date=today,
        postings=[
            {"account_id": a["id"], "direction": "DEBIT", "amount": "5.00", "currency": "GBP"},
            {"account_id": fees["id"], "direction": "CREDIT", "amount": "5.00", "currency": "GBP"},
        ],
    )
    print(f"  posted {fee['reference']} id={fee['id']}")

    banner("5. Account balances")
    show_balances(client, accounts)

    banner("6. Trial balance")
    tb = show_trial_balance(client)
    assert tb["balanced"]

    banner("7. Reverse the service fee")
    reversal = client.reverse(fee["id"], "Fee waived (demo)", f"rev-{run}")
    print(
        f"  HTTP {reversal.status_code} reversal id={reversal.json()['id']} reversal_of={reversal.json()['reversal_of']}"
    )
    assert reversal.status_code == 201
    again = client.reverse(fee["id"], "Fee waived (demo)", f"rev2-{run}")
    print(f"  second reversal attempt -> HTTP {again.status_code} {again.json()['error']['code']}")
    assert again.status_code == 409
    print("  audit trail of the fee entry:")
    for event in client.audit_events(fee["id"]):
        print(
            f"    {event['occurred_at']}  {event['event_type']:<18} correlation={event['correlation_id']}"
        )

    banner("8. Final balances and trial balance")
    show_balances(client, accounts)
    tb = show_trial_balance(client)
    check = client.ledger_check()
    print(
        f"  ledger-check balanced={check['balanced']} currencies={[c['currency'] for c in check['currencies']]}"
    )
    assert tb["balanced"] and check["balanced"]
    print("\nDemo complete: the ledger remained balanced throughout.")


if __name__ == "__main__":
    main()
