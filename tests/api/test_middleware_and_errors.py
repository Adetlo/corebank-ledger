from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from corebank.api.app import create_app
from corebank.config import Settings


def test_correlation_id_is_echoed_or_generated(client: TestClient) -> None:
    r = client.get("/health/live", headers={"X-Correlation-ID": "my-trace-001"})
    assert r.headers["X-Correlation-ID"] == "my-trace-001"
    r = client.get("/health/live", headers={"X-Request-ID": "req-9"})
    assert r.headers["X-Correlation-ID"] == "req-9"
    r = client.get("/health/live", headers={"X-Correlation-ID": "bad value with spaces!"})
    assert (
        r.headers["X-Correlation-ID"] != "bad value with spaces!"
        and len(r.headers["X-Correlation-ID"]) == 32
    )
    r = client.get("/health/live")
    assert len(r.headers["X-Correlation-ID"]) == 32


def test_request_size_limit(settings: Settings, db, dispatcher) -> None:  # type: ignore[no-untyped-def]
    small = settings.model_copy(update={"max_request_bytes": 200})
    app = create_app(small, engine=db, dispatcher=dispatcher)
    with TestClient(app) as client:
        big = {"account_name": "x" * 500, "account_type": "ASSET", "currency": "GBP"}
        r = client.post("/api/v1/accounts", json=big)
        assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
        ok = client.post(
            "/api/v1/accounts",
            json={"account_name": "small", "account_type": "ASSET", "currency": "GBP"},
        )
        assert ok.status_code == 201
        # Streamed body without a Content-Length header is still capped.
        r = client.post(
            "/api/v1/accounts",
            content=iter(
                [
                    b'{"account_name": "'
                    + b"y" * 400
                    + b'", "account_type": "ASSET", "currency": "GBP"}'
                ]
            ),
            headers={"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
        )
        assert r.status_code == 413


def test_unhandled_and_database_errors_are_masked(app: FastAPI) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/db-down")
    def db_down() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/boom")
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "secret internal detail" not in r.text
        r = client.get("/db-down")
        assert r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "connection refused" not in r.text
