from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.helpers import TODAY, create_account, fund, key, post_journal


def test_post_journal_entry_success(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    customer = create_account(client, "C", "LIABILITY")
    response = post_journal(
        client,
        [(settlement["id"], "DEBIT", "1000.00"), (customer["id"], "CREDIT", "1000.00")],
        reference="DEP-DEMO-0001",
        description="Synthetic deposit",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "POSTED" and body["currency"] == "GBP"
    assert body["total_debits"] == "1000.00" == body["total_credits"]
    assert len(body["postings"]) == 2 and body["posted_at"]
    assert body["reversal_of"] is None and body["reversed_by"] is None
    assert body["value_date"] == TODAY.isoformat()
    assert client.get(f"/api/v1/journal-entries/{body['id']}").json()["id"] == body["id"]


def test_unbalanced_entry_rejected(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    customer = create_account(client, "C", "LIABILITY")
    response = post_journal(
        client, [(settlement["id"], "DEBIT", "999.99"), (customer["id"], "CREDIT", "1000.00")]
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "UNBALANCED_JOURNAL"
    assert error["message"] == "Journal entry debits and credits must balance."
    assert error["details"]["difference"] == "-0.01"
    assert client.get("/api/v1/journal-entries").json()["total"] == 0


def test_validation_errors(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    customer = create_account(client, "C", "LIABILITY")
    base = {"reference": "R", "booking_date": "2026-10-13"}
    legs = [
        {"account_id": settlement["id"], "direction": "DEBIT", "amount": 10.5, "currency": "GBP"},
        {"account_id": customer["id"], "direction": "CREDIT", "amount": "10.50", "currency": "GBP"},
    ]
    r = client.post(
        "/api/v1/journal-entries",
        json={**base, "postings": legs},
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AMOUNT"
    legs[0]["amount"] = "10.505"
    r = client.post(
        "/api/v1/journal-entries",
        json={**base, "postings": legs},
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AMOUNT"
    legs[0]["amount"] = "-10.50"
    r = client.post(
        "/api/v1/journal-entries",
        json={**base, "postings": legs},
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_AMOUNT"
    legs[0]["amount"] = "10.50"
    r = client.post(
        "/api/v1/journal-entries",
        json={**base, "postings": legs[:1]},
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    legs[0]["direction"] = "SIDEWAYS"
    r = client.post(
        "/api/v1/journal-entries",
        json={**base, "postings": legs},
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    legs[0]["direction"] = "DEBIT"
    r = client.post(
        "/api/v1/journal-entries",
        json={**base, "postings": legs, "metadata": {f"k{i}": i for i in range(21)}},
        headers={"Idempotency-Key": key()},
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/journal-entries",
        content=b"{not json",
        headers={"Idempotency-Key": key(), "Content-Type": "application/json"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_currency_mismatch_and_unknown_account(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    usd = create_account(client, "U", "LIABILITY", currency="USD")
    r = post_journal(client, [(settlement["id"], "DEBIT", "1.00"), (usd["id"], "CREDIT", "1.00")])
    assert r.status_code == 422 and r.json()["error"]["code"] == "CURRENCY_MISMATCH"
    r = post_journal(
        client, [(settlement["id"], "DEBIT", "1.00"), (str(uuid4()), "CREDIT", "1.00")]
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_idempotency_header_behaviour(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    customer = create_account(client, "C", "LIABILITY")
    legs = [(settlement["id"], "DEBIT", "10.00"), (customer["id"], "CREDIT", "10.00")]
    missing = client.post(
        "/api/v1/journal-entries",
        json={
            "reference": "R",
            "booking_date": "2026-10-13",
            "postings": [
                {"account_id": a, "direction": d, "amount": m, "currency": "GBP"}
                for a, d, m in legs
            ],
        },
    )
    assert (
        missing.status_code == 400 and missing.json()["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"
    )

    first = post_journal(client, legs, idempotency_key="idem-1")
    assert first.status_code == 201 and "Idempotent-Replayed" not in first.headers
    replay = post_journal(client, legs, idempotency_key="idem-1")
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert client.get("/api/v1/journal-entries").json()["total"] == 1

    conflict = post_journal(
        client,
        [(settlement["id"], "DEBIT", "11.00"), (customer["id"], "CREDIT", "11.00")],
        idempotency_key="idem-1",
    )
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )
    assert client.get(f"/api/v1/accounts/{customer['id']}/balance").json()["balance"] == "10.00"

    events = client.get(f"/api/v1/journal-entries/{first.json()['id']}/audit-events").json()
    assert [e["event_type"] for e in events] == [
        "JOURNAL_CREATED",
        "JOURNAL_POSTED",
        "IDEMPOTENT_REPLAY",
    ]
    assert all(e["correlation_id"] for e in events)


def test_search_filters_and_pagination(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    a = create_account(client, "A", "LIABILITY")
    b = create_account(client, "B", "LIABILITY")
    from datetime import date

    fund(client, settlement["id"], a["id"], "100.00")
    for i in range(3):
        r = post_journal(
            client,
            [(a["id"], "DEBIT", "1.00"), (b["id"], "CREDIT", "1.00")],
            reference=f"T-{i}",
            booking_date=date(2026, 1, 1 + i),
        )
        assert r.status_code == 201
    assert client.get("/api/v1/journal-entries").json()["total"] == 4
    page = client.get("/api/v1/journal-entries", params={"limit": 2, "offset": 0}).json()
    assert len(page["items"]) == 2 and page["total"] == 4
    page = client.get("/api/v1/journal-entries", params={"limit": 2, "offset": 2}).json()
    assert len(page["items"]) == 2
    assert client.get("/api/v1/journal-entries", params={"reference": "T-1"}).json()["total"] == 1
    assert (
        client.get("/api/v1/journal-entries", params={"account_id": b["id"]}).json()["total"] == 3
    )
    assert (
        client.get("/api/v1/journal-entries", params={"account_id": settlement["id"]}).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get(
            "/api/v1/journal-entries",
            params={"booking_date_from": "2026-01-02", "booking_date_to": "2026-01-03"},
        ).json()["total"]
        == 2
    )
    assert client.get("/api/v1/journal-entries", params={"status": "POSTED"}).json()["total"] == 4
    assert client.get("/api/v1/journal-entries", params={"status": "REVERSED"}).json()["total"] == 0
    assert client.get("/api/v1/journal-entries", params={"currency": "usd"}).json()["total"] == 0
    assert client.get(f"/api/v1/journal-entries/{uuid4()}").status_code == 404


def test_reverse_endpoint(client: TestClient) -> None:
    settlement = create_account(client, "S", "ASSET")
    a = create_account(client, "A", "LIABILITY")
    fees = create_account(client, "Fees", "INCOME")
    fund(client, settlement["id"], a["id"], "100.00")
    fee = post_journal(
        client, [(a["id"], "DEBIT", "5.00"), (fees["id"], "CREDIT", "5.00")], reference="FEE"
    ).json()
    url = f"/api/v1/journal-entries/{fee['id']}/reverse"
    missing = client.post(url, json={"reason": "x"})
    assert missing.status_code == 400
    first = client.post(url, json={"reason": "waived"}, headers={"Idempotency-Key": "rv-1"})
    assert first.status_code == 201, first.text
    assert (
        first.json()["reversal_of"] == fee["id"]
        and first.json()["metadata"]["reversal_reason"] == "waived"
    )
    replay = client.post(url, json={"reason": "waived"}, headers={"Idempotency-Key": "rv-1"})
    assert replay.status_code == 200 and replay.headers["Idempotent-Replayed"] == "true"
    second = client.post(url, headers={"Idempotency-Key": "rv-2"})
    assert (
        second.status_code == 409 and second.json()["error"]["code"] == "JOURNAL_ALREADY_REVERSED"
    )
    assert client.get(f"/api/v1/journal-entries/{fee['id']}").json()["status"] == "REVERSED"
    assert client.get("/api/v1/journal-entries", params={"status": "REVERSED"}).json()["total"] == 1
    assert (
        client.post(
            f"/api/v1/journal-entries/{uuid4()}/reverse", headers={"Idempotency-Key": "rv-3"}
        ).status_code
        == 404
    )
