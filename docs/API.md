# API Reference

Base path: `/api/v1`. Interactive docs: `/docs` (Swagger UI) and `/redoc`.
All responses are JSON. Amounts are decimal **strings** (`"1000.00"`).

## Conventions

| Concern            | Behaviour                                                                                       |
|--------------------|--------------------------------------------------------------------------------------------------|
| Correlation        | Send `X-Correlation-ID` (or `X-Request-ID`); it is echoed back and stored on audit events. One is generated if absent. |
| Idempotency        | `Idempotency-Key` header (≤ 128 chars) is **required** on `POST /journal-entries`, `POST /transfers`, `POST /journal-entries/{id}/reverse`, `POST /payments/instructions`. Replays return `200` with `Idempotent-Replayed: true`. |
| Actor              | Optional `X-Actor` header is recorded on audit events (informational; no authentication in v1). |
| Pagination         | `limit` (1..200, default 50) and `offset` (≥ 0); responses carry `items`, `total`, `limit`, `offset`. |
| Request size       | Bodies above `MAX_REQUEST_BYTES` (default 256 KiB) are rejected with `413 PAYLOAD_TOO_LARGE`.   |
| Unknown fields     | Rejected (`422 VALIDATION_ERROR`).                                                              |

### Error envelope

```json
{
  "error": {
    "code": "UNBALANCED_JOURNAL",
    "message": "Journal entry debits and credits must balance.",
    "correlation_id": "0f2a1a3c4d5e6f708192a3b4c5d6e7f8",
    "details": {"currency": "GBP", "total_debits": "999.99", "total_credits": "1000.00", "difference": "-0.01"}
  }
}
```

### Error codes

| Code                        | HTTP | When                                                                 |
|-----------------------------|------|----------------------------------------------------------------------|
| `VALIDATION_ERROR`          | 422  | Schema/shape problems; `details.errors[]` lists locations            |
| `UNSUPPORTED_CURRENCY`      | 422  | Currency not in GBP, USD, EUR, JPY, CHF, SGD, AUD                    |
| `INVALID_AMOUNT`            | 422  | Float, non-positive, non-finite or over-precise amount               |
| `CURRENCY_MISMATCH`         | 422  | Postings/accounts not in one currency                                |
| `UNBALANCED_JOURNAL`        | 422  | Debits ≠ credits, one-sided or < 2 postings                          |
| `INVALID_TRANSFER`          | 422  | Same account, or accounts with different normal balances             |
| `MISSING_IDEMPOTENCY_KEY`   | 400  | Financial mutation without the header                                |
| `ACCOUNT_NOT_FOUND`         | 404  |                                                                      |
| `JOURNAL_NOT_FOUND`         | 404  | Also for `GET /transfers/{id}` when the entry is not a transfer      |
| `ACCOUNT_CLOSED`            | 409  | Posting to a closed account                                          |
| `ACCOUNT_FROZEN`            | 409  | Posting to a frozen account                                          |
| `ACCOUNT_NOT_EMPTY`         | 409  | Closing an account with a non-zero balance                           |
| `INVALID_STATUS_TRANSITION` | 409  | e.g. reopening a closed account                                      |
| `INSUFFICIENT_FUNDS`        | 409  | Entry would overdraw an account with `allow_negative_balance=false`  |
| `IDEMPOTENCY_CONFLICT`      | 409  | Same key, different payload                                          |
| `JOURNAL_NOT_POSTED`        | 409  | Reversing a non-posted entry                                         |
| `JOURNAL_ALREADY_REVERSED`  | 409  | Second reversal attempt                                              |
| `IMMUTABLE_POSTING`         | 409  | Attempt to alter a posted entry                                      |
| `CONCURRENCY_CONFLICT`      | 409  | Optimistic version mismatch; retry                                   |
| `PAYLOAD_TOO_LARGE`         | 413  |                                                                      |
| `INTERNAL_ERROR`            | 500  | Unexpected failure; details are logged, never returned               |
| `SERVICE_UNAVAILABLE`       | 503  | Database unreachable                                                 |

## Health

| Method | Path            | Notes                                              |
|--------|-----------------|----------------------------------------------------|
| GET    | `/health/live`  | Process is up                                      |
| GET    | `/health/ready` | `200` only if `SELECT 1` succeeds; else `503`      |

## Accounts

| Method | Path                               | Notes                                            |
|--------|------------------------------------|--------------------------------------------------|
| POST   | `/accounts`                        | Create; number generated (`SYN-##########-#`)    |
| GET    | `/accounts`                        | Filters: `account_type`, `currency`, `status`    |
| GET    | `/accounts/{id}`                   |                                                  |
| GET    | `/accounts/{id}/balance`           | `?as_of_date=YYYY-MM-DD`; derived from postings  |
| POST   | `/accounts/{id}/status`            | `{"status": "FROZEN"|"ACTIVE"|"CLOSED"}`         |

```bash
curl -s -X POST http://localhost:8000/api/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"account_name": "Synthetic Customer Current Account", "account_type": "LIABILITY", "currency": "GBP"}'
```

```json
{
  "id": "6f1c0d7e-3b7a-4b6f-9b1e-0c5a1d2e3f40",
  "account_number": "SYN-4829103771-5",
  "account_name": "Synthetic Customer Current Account",
  "account_type": "LIABILITY",
  "currency": "GBP",
  "status": "ACTIVE",
  "normal_balance": "CREDIT",
  "allow_negative_balance": false,
  "version": 1,
  "created_at": "2026-10-13T09:00:00Z",
  "updated_at": "2026-10-13T09:00:00Z"
}
```

Balance:

```json
{
  "account_id": "6f1c0d7e-...",
  "currency": "GBP",
  "normal_balance": "CREDIT",
  "debit_total": "255.00",
  "credit_total": "1000.00",
  "balance": "745.00",
  "as_of_date": null,
  "posting_count": 3
}
```

## Journal entries

| Method | Path                                   | Notes                                                  |
|--------|----------------------------------------|--------------------------------------------------------|
| POST   | `/journal-entries`                     | Post a balanced entry (Idempotency-Key required)       |
| GET    | `/journal-entries`                     | Filters: `reference`, `status`, `account_id`, `booking_date_from`, `booking_date_to`, `currency` |
| GET    | `/journal-entries/{id}`                |                                                        |
| GET    | `/journal-entries/{id}/audit-events`   | Append-only trail for the entry                        |
| POST   | `/journal-entries/{id}/reverse`        | Body optional: `{"reason", "reference", "booking_date"}` |

```bash
curl -s -X POST http://localhost:8000/api/v1/journal-entries \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: dep-demo-0001' \
  -d '{
    "reference": "DEP-DEMO-0001",
    "description": "Synthetic deposit",
    "booking_date": "2026-10-13",
    "postings": [
      {"account_id": "<settlement-asset-id>", "direction": "DEBIT",  "amount": "1000.00", "currency": "GBP"},
      {"account_id": "<customer-liability-id>", "direction": "CREDIT", "amount": "1000.00", "currency": "GBP"}
    ]
  }'
```

Response (`201`, or `200` + `Idempotent-Replayed: true` on replay):

```json
{
  "id": "0b3e...",
  "reference": "DEP-DEMO-0001",
  "description": "Synthetic deposit",
  "booking_date": "2026-10-13",
  "value_date": "2026-10-13",
  "status": "POSTED",
  "currency": "GBP",
  "total_debits": "1000.00",
  "total_credits": "1000.00",
  "postings": [
    {"id": "...", "journal_entry_id": "0b3e...", "account_id": "...", "direction": "DEBIT", "amount": "1000.00", "currency": "GBP", "created_at": "..."},
    {"id": "...", "journal_entry_id": "0b3e...", "account_id": "...", "direction": "CREDIT", "amount": "1000.00", "currency": "GBP", "created_at": "..."}
  ],
  "idempotency_key": "dep-demo-0001",
  "metadata": {},
  "reversal_of": null,
  "reversed_by": null,
  "created_at": "...",
  "posted_at": "..."
}
```

## Transfers

| Method | Path                | Notes                                                      |
|--------|---------------------|------------------------------------------------------------|
| POST   | `/transfers`        | `source_account_id`, `destination_account_id`, `amount`, `currency`, `reference`, `value_date?`, `booking_date?`, `description?`, `metadata?` |
| GET    | `/transfers/{id}`   | `id` equals the journal entry id                           |

```bash
curl -s -X POST http://localhost:8000/api/v1/transfers \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: trf-demo-0001' \
  -d '{"source_account_id": "<customer-a>", "destination_account_id": "<customer-b>",
       "amount": "250.00", "currency": "GBP", "reference": "TRF-DEMO-0001", "value_date": "2026-10-13"}'
```

The response embeds the journal entry it booked (`journal_entry`), with
`metadata.kind = "TRANSFER"`.

## Reconciliation

| Method | Path                               | Notes                                            |
|--------|------------------------------------|--------------------------------------------------|
| GET    | `/reconciliation/trial-balance`    | `?currency=GBP&as_of_date=YYYY-MM-DD`            |
| GET    | `/reconciliation/ledger-check`     | All currencies + list of unbalanced journal ids  |

```json
{
  "currency": "GBP",
  "as_of_date": null,
  "accounts": [
    {"account_id": "...", "account_number": "SYN-...", "account_name": "Cash / Settlement GBP", "account_type": "ASSET",
     "normal_balance": "DEBIT", "currency": "GBP", "debit_total": "1000.00", "credit_total": "0.00", "net_balance": "1000.00"}
  ],
  "total_debits": "1260.00",
  "total_credits": "1260.00",
  "difference": "0.00",
  "balanced": true
}
```

## Payments (ISO 20022-inspired simplified model)

| Method | Path                      | Notes                                                       |
|--------|---------------------------|-------------------------------------------------------------|
| POST   | `/payments/instructions`  | `payment_id`, `end_to_end_id`, `debtor_account`, `creditor_account`, `amount`, `currency`, `requested_execution_date?`, `remittance_information?` |

Adapts the instruction into a transfer; `end_to_end_id` becomes the ledger
reference. This is **not** an ISO 20022 implementation and claims no
compliance.
