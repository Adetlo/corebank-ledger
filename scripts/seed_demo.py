"""Seed a synthetic chart of accounts through the public API.

Usage::

    uv run python scripts/seed_demo.py                 # against http://127.0.0.1:8000
    API_BASE_URL=http://localhost:8000 uv run python scripts/seed_demo.py

All names and numbers are fictional. Re-running creates a fresh set of accounts
(account numbers are generated) and prints their ids.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _client import LedgerClient

SEED_ACCOUNTS: list[dict[str, Any]] = [
    {"key": "settlement", "name": "Cash / Settlement GBP", "type": "ASSET"},
    {"key": "customer_a", "name": "Synthetic Customer A", "type": "LIABILITY"},
    {"key": "customer_b", "name": "Synthetic Customer B", "type": "LIABILITY"},
    {"key": "fee_income", "name": "Fee Income", "type": "INCOME"},
    {"key": "opex", "name": "Operating Expense", "type": "EXPENSE"},
    {
        "key": "suspense",
        "name": "Suspense Account",
        "type": "LIABILITY",
        "allow_negative_balance": True,
    },
]


def seed(client: LedgerClient, currency: str = "GBP") -> dict[str, dict[str, Any]]:
    accounts: dict[str, dict[str, Any]] = {}
    for spec in SEED_ACCOUNTS:
        extra = (
            {"allow_negative_balance": spec["allow_negative_balance"]}
            if "allow_negative_balance" in spec
            else {}
        )
        account = client.create_account(spec["name"], spec["type"], currency, **extra)
        accounts[spec["key"]] = account
        print(
            f"  created {account['account_number']}  {account['account_type']:<9} {account['account_name']}"
        )
    return accounts


def main() -> None:
    client = LedgerClient()
    client.wait_ready()
    print(f"Seeding synthetic accounts at {client.base_url}")
    accounts = seed(client)
    out = Path(".demo-accounts.json")
    out.write_text(json.dumps({k: v["id"] for k, v in accounts.items()}, indent=2))
    print(f"Wrote account ids to {out}")


if __name__ == "__main__":
    main()
