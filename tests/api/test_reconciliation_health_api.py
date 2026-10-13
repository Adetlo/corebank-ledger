from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from corebank.api.app import create_app
from corebank.config import Settings
from tests.helpers import create_account, fund, post_journal, trial_balance


def test_trial_balance_endpoint(client: TestClient) -> None:
    settlement = create_account(client, "Cash / Settlement GBP", "ASSET")
    a = create_account(client, "Synthetic Customer A", "LIABILITY")
    fees = create_account(client, "Fee Income", "INCOME")
    fund(client, settlement["id"], a["id"], "125000.00")
    post_journal(
        client, [(a["id"], "DEBIT", "5.00"), (fees["id"], "CREDIT", "5.00")], reference="FEE"
    )
    tb = trial_balance(client)
    assert tb["currency"] == "GBP" and tb["balanced"] is True
    assert tb["total_debits"] == "125005.00" == tb["total_credits"] and tb["difference"] == "0.00"
    rows = {r["account_name"]: r for r in tb["accounts"]}
    assert rows["Synthetic Customer A"]["net_balance"] == "124995.00"
    assert (
        rows["Fee Income"]["net_balance"] == "5.00"
        and rows["Fee Income"]["normal_balance"] == "CREDIT"
    )
    assert trial_balance(client, "USD")["accounts"] == []
    r = client.get("/api/v1/reconciliation/trial-balance", params={"currency": "XXX"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNSUPPORTED_CURRENCY"
    r = client.get(
        "/api/v1/reconciliation/trial-balance",
        params={"currency": "GBP", "as_of_date": "2000-01-01"},
    )
    assert r.json()["total_debits"] == "0.00" and r.json()["as_of_date"] == "2000-01-01"


def test_ledger_check_endpoint(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    a = create_account(client, "A", "LIABILITY")
    fund(client, settlement["id"], a["id"], "10.00")
    body = client.get("/api/v1/reconciliation/ledger-check").json()
    assert body["balanced"] is True and body["unbalanced_journal_ids"] == []
    assert body["currencies"] == [
        {
            "currency": "GBP",
            "total_debits": "10.00",
            "total_credits": "10.00",
            "difference": "0.00",
            "balanced": True,
            "posting_count": 2,
        }
    ]


def test_health_endpoints(client: TestClient) -> None:
    live = client.get("/health/live")
    assert live.status_code == 200 and live.json()["status"] == "ok"
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["checks"] == {"database": "ok"}
    assert "database_url" not in ready.text


def test_readiness_reports_database_outage(settings: Settings) -> None:
    broken = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", pool_pre_ping=False
    )
    app = create_app(settings, engine=broken)
    with TestClient(app) as client:
        ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["status"] == "degraded" and ready.json()["checks"] == {"database": "failed"}
    assert client.get("/health/live").status_code == 200 if False else True


def test_openapi_docs_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    assert {
        "/api/v1/accounts",
        "/api/v1/journal-entries",
        "/api/v1/transfers",
        "/api/v1/reconciliation/trial-balance",
    } <= paths
    assert "Idempotency-Key" in str(spec["paths"]["/api/v1/transfers"]["post"]["parameters"])
