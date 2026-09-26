"""Tiny HTTP client helper shared by the demo scripts (talks to a running API)."""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class LedgerClient:
    """Thin wrapper around the REST API with automatic Idempotency-Key headers."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=10.0)

    def _check(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            print(f"API error {response.status_code}: {response.text}", file=sys.stderr)
            raise SystemExit(1)
        return response.json()

    def wait_ready(self, attempts: int = 30) -> None:
        import time

        for _ in range(attempts):
            try:
                if self._http.get("/health/ready").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        print(f"API at {self.base_url} is not ready", file=sys.stderr)
        raise SystemExit(1)

    def create_account(
        self, name: str, account_type: str, currency: str = "GBP", **extra: Any
    ) -> dict[str, Any]:
        body = {"account_name": name, "account_type": account_type, "currency": currency, **extra}
        return dict(self._check(self._http.post("/api/v1/accounts", json=body)))

    def list_accounts(self, **params: Any) -> dict[str, Any]:
        return dict(self._check(self._http.get("/api/v1/accounts", params=params)))

    def post_journal(
        self,
        reference: str,
        description: str,
        booking_date: str,
        postings: list[dict[str, str]],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "reference": reference,
            "description": description,
            "booking_date": booking_date,
            "postings": postings,
        }
        headers = {"Idempotency-Key": idempotency_key or f"demo-{uuid.uuid4()}"}
        return dict(
            self._check(self._http.post("/api/v1/journal-entries", json=body, headers=headers))
        )

    def post_journal_raw(self, body: dict[str, Any], idempotency_key: str) -> httpx.Response:
        return self._http.post(
            "/api/v1/journal-entries", json=body, headers={"Idempotency-Key": idempotency_key}
        )

    def transfer(self, body: dict[str, Any], idempotency_key: str) -> httpx.Response:
        return self._http.post(
            "/api/v1/transfers", json=body, headers={"Idempotency-Key": idempotency_key}
        )

    def reverse(self, journal_id: str, reason: str, idempotency_key: str) -> httpx.Response:
        return self._http.post(
            f"/api/v1/journal-entries/{journal_id}/reverse",
            json={"reason": reason},
            headers={"Idempotency-Key": idempotency_key},
        )

    def balance(self, account_id: str) -> dict[str, Any]:
        return dict(self._check(self._http.get(f"/api/v1/accounts/{account_id}/balance")))

    def trial_balance(self, currency: str = "GBP") -> dict[str, Any]:
        return dict(
            self._check(
                self._http.get(
                    "/api/v1/reconciliation/trial-balance", params={"currency": currency}
                )
            )
        )

    def ledger_check(self) -> dict[str, Any]:
        return dict(self._check(self._http.get("/api/v1/reconciliation/ledger-check")))

    def audit_events(self, journal_id: str) -> list[dict[str, Any]]:
        return list(
            self._check(self._http.get(f"/api/v1/journal-entries/{journal_id}/audit-events"))
        )
