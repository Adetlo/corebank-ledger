# CoreBank Ledger

CoreBank Ledger is a production-style educational double-entry ledger service
demonstrating the engineering controls behind financial transaction systems.

Built with Python 3.12, FastAPI and PostgreSQL, it records every movement of
value as a balanced journal entry and derives all balances from those entries.
The code is small enough to read in an afternoon and the test suite proves the
controls rather than just the happy path.

> **Disclaimer.** This project is an independent educational implementation
> using synthetic data and generic banking concepts. It is not affiliated
> with, derived from, or representative of any production banking system.

**What this demonstrates**

* Double-entry integrity: every posted entry satisfies `SUM(debits) == SUM(credits)`
* Idempotent processing: persistent `Idempotency-Key` handling, safe under concurrent retries
* Atomic transactions: journal, postings, audit and idempotency rows commit together or not at all
* Immutable postings: no updates or deletes once posted
* Reversals: corrections are new, linked entries; history is never rewritten
* Reconciliation: trial balance and ledger-wide integrity check derived from postings
* Concurrency-aware processing: ordered row locks, optimistic versioning, race tests
* Automated testing: unit, integration on real PostgreSQL, property-based

---

## Contents

1. [Project overview](#1-project-overview)
2. [Why this project exists](#2-why-this-project-exists)
3. [Banking and ledger concepts demonstrated](#3-banking-and-ledger-concepts-demonstrated)
4. [Architecture](#4-architecture)
5. [Ledger invariants](#5-ledger-invariants)
6. [Technology stack](#6-technology-stack)
7. [Repository structure](#7-repository-structure)
8. [Data model](#8-data-model)
9. [Quick start](#9-quick-start)
10. [Docker quick start](#10-docker-quick-start)
11. [API examples](#11-api-examples)
12. [Testing](#12-testing)
13. [Design decisions](#13-design-decisions)
14. [Limitations](#14-limitations)
15. [Disclaimer](#15-disclaimer)

---

## 1. Project overview

CoreBank Ledger is a small but complete **core ledger**: the component of a
banking platform that records every movement of value as balanced
double-entry journal entries and answers "what is the balance of this
account?" by deriving it from those entries.

It exposes a REST API to:

* create ledger accounts (asset, liability, equity, income, expense),
* post balanced journal entries,
* transfer value between accounts,
* reverse posted entries without ever editing history,
* derive balances and trial balances,
* run ledger-wide integrity checks,
* query an append-only audit trail.

Every financial mutation is **atomic**, **idempotent** and **immutable once
posted**. The rules are enforced in the domain model, re-checked in the
application transaction and reinforced by PostgreSQL constraints and triggers.

## 2. Why this project exists

Most "banking" sample projects are CRUD applications with a `balance` column.
Real ledgers are different: money is never updated in place, every change is
a balanced pair of postings, retries must be safe, and the books must
reconcile to zero at any point in time.

This repository exists to demonstrate those properties with code that can be
read in an afternoon, run with one command, and verified by a test suite that
proves the invariants rather than just the happy path. It is intended as an
engineering portfolio piece for senior engineering, fintech, banking
technology and architecture roles.

## 3. Banking and ledger concepts demonstrated

| Concept                     | Where                                                                      |
|-----------------------------|----------------------------------------------------------------------------|
| Double-entry accounting     | `domain/ledger.py`: every entry has debits equal to credits                |
| Chart of accounts and normal balances | `domain/accounts.py`: ASSET/EXPENSE are debit-normal, LIABILITY/EQUITY/INCOME credit-normal |
| Journal entries and postings| `JournalEntry` with immutable `Posting` legs                               |
| Transfers as journal entries| `domain/transactions.py` translates "move value A→B" into balanced legs     |
| Idempotency                 | Persistent `Idempotency-Key` records written in the posting transaction    |
| Atomicity                   | One database transaction per use case (`UnitOfWork`)                       |
| Immutability and reversals  | No updates/deletes; corrections are linked reversal entries                |
| Balance derivation          | Balances are `SUM` over postings, optionally as of a date                  |
| Reconciliation              | Trial balance per currency; ledger check across currencies                 |
| Concurrency control         | Row locks in deterministic order; optimistic versioning; race tests        |
| Available-funds control     | Configurable per account; enforced under lock                              |
| Auditability                | Append-only audit events with correlation ids and actors                   |
| Financial precision         | `Decimal` money with per-currency minor units; floats rejected             |
| Payment message adaptation  | ISO 20022-inspired simplified instruction → internal transfer              |
| Domain events / outbox      | In-process events now; transactional outbox documented                     |

## 4. Architecture

Clean, layered architecture with dependencies pointing inwards. Full detail
in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

```mermaid
flowchart LR
    Client[Client] -->|HTTP / JSON| API[FastAPI API<br/>schemas · error envelope<br/>correlation id · size limits]
    API --> Application[Application services<br/>accounts · posting · transfers<br/>reversals · reconciliation]
    Application --> Domain[Ledger domain<br/>Money · Account · JournalEntry · Posting]
    Application --> UoW[Unit of Work<br/>one transaction per use case]
    UoW --> Repo[Repositories]
    Repo --> DB[(PostgreSQL<br/>constraints · triggers)]
    Domain --> Invariants[Ledger invariants<br/>Σ debits = Σ credits]
    Application --> Idem[Idempotency records]
    Application --> Audit[Audit events]
    Application --> Events[Domain events]
    Events -.->|future| Outbox[(Outbox → broker)]
```

### Transaction flow

```mermaid
flowchart TD
    C[Client request<br/>+ Idempotency-Key] --> I{Idempotency check}
    I -->|seen, same payload| R0[Replay stored result<br/>200 + Idempotent-Replayed]
    I -->|seen, different payload| X0[409 IDEMPOTENCY_CONFLICT]
    I -->|new| V[Validation<br/>schema · currency · accounts]
    V --> T[BEGIN database transaction]
    T --> L[Lock accounts FOR UPDATE<br/>sorted by id]
    L --> B[Balanced journal<br/>Σ debits = Σ credits]
    B --> F[Available-funds check]
    F --> P[Insert journal + postings]
    P --> A[Audit events<br/>+ idempotency record]
    A --> K[COMMIT<br/>deferred trigger re-checks balance]
    K --> E[Dispatch domain events]
    E --> R[201 Created]
    B -.->|unbalanced| RB[ROLLBACK → 422]
    F -.->|insufficient| RB2[ROLLBACK → 409]
```

## 5. Ledger invariants

Documented with enforcement points and proving tests in
[`docs/LEDGER_INVARIANTS.md`](docs/LEDGER_INVARIANTS.md).

| # | Invariant                                          | Enforced in                                      |
|---|----------------------------------------------------|--------------------------------------------------|
| 1 | `SUM(debits) == SUM(credits)` for every posted entry | domain, application, deferred DB trigger       |
| 2 | Posted entries and postings are immutable          | frozen dataclasses, no edit endpoints, DB triggers |
| 3 | A transaction posts atomically                     | unit of work, PostgreSQL transaction             |
| 4 | Idempotent retries cannot duplicate economic events| persistent keys + unique constraint              |
| 5 | Reversals preserve history                         | new linked entry; original never changes         |
| 6 | Balances are derived from ledger postings          | no balance column; `SUM` queries                 |

## 6. Technology stack

| Layer           | Choice                                                     |
|-----------------|------------------------------------------------------------|
| Language        | Python 3.12                                                |
| API             | FastAPI, Pydantic v2                                       |
| Persistence     | SQLAlchemy 2.x, PostgreSQL 16, psycopg 3                   |
| Testing         | pytest, Hypothesis, FastAPI TestClient, embedded PostgreSQL (`pgserver`) |
| Quality         | ruff, mypy (strict), bandit, pip-audit                     |
| Packaging       | uv + `pyproject.toml`                                      |
| Containers      | Docker multi-stage image, Docker Compose                   |
| CI              | GitHub Actions with a PostgreSQL service container         |

## 7. Repository structure

```
corebank-ledger/
├── src/corebank/
│   ├── api/                  # FastAPI routes, dependencies, errors, middleware, presenters
│   │   └── routes/           # accounts, journal_entries, transfers, reconciliation, payments, health
│   ├── application/          # use cases: account, posting, transfer, reversal, reconciliation services
│   │   ├── unit_of_work.py   # one transaction per use case, post-commit event dispatch
│   │   └── idempotency.py    # persistent Idempotency-Key guard
│   ├── domain/               # money, accounts, ledger (journal/postings), transactions, events, exceptions
│   ├── infrastructure/       # SQLAlchemy engine, ORM models, repositories
│   ├── integrations/         # ISO 20022-inspired simplified payment adapter
│   ├── schemas/              # pydantic request/response DTOs
│   ├── config.py             # environment configuration
│   ├── logging.py            # structured JSON logging with correlation ids
│   └── main.py               # ASGI entry point
├── tests/
│   ├── unit/                 # domain and config tests (no database)
│   ├── integration/          # services against PostgreSQL: atomicity, locks, races
│   └── property/             # Hypothesis properties: balancing, reversal, idempotency
├── examples/                 # request bodies
├── docs/                     # ARCHITECTURE, LEDGER_INVARIANTS, DATA_MODEL, OUTBOX
├── .github/workflows/ci.yml  # lint, types, tests + coverage, audits, image build
├── Dockerfile · docker-compose.yml · pyproject.toml
├── .env.example · .gitignore · LICENSE
```

## 8. Data model

Five tables, UUID keys and constraints that mirror the domain rules. See
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).

```mermaid
erDiagram
    accounts ||--o{ postings : has
    journal_entries ||--|{ postings : contains
    journal_entries o|--o| journal_entries : "reversal_of / reversed_by"
    idempotency_records }o--o| journal_entries : resource_id
    audit_events }o--o| journal_entries : entity_id
```

| Table                 | Purpose                                                          |
|-----------------------|------------------------------------------------------------------|
| `accounts`            | Chart of accounts; `normal_balance` derived from type; no balance column |
| `journal_entries`     | One accounting transaction; status, dates, reversal links, metadata |
| `postings`            | Debit/credit legs, `NUMERIC(19,4) > 0`, immutable                |
| `idempotency_records` | `(scope, key)` unique; payload hash; stored result               |
| `audit_events`        | Append-only trail with correlation id and actor                  |

## 9. Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for
you) and a PostgreSQL 16 instance for running the API. **Tests need nothing
extra**: they start an embedded PostgreSQL automatically.

```bash
uv sync                                  # dependencies + dev tools
uv run pytest                            # full suite against embedded PostgreSQL

cp .env.example .env                     # point DATABASE_URL at your PostgreSQL
uv run uvicorn corebank.main:app --reload
open http://127.0.0.1:8000/docs
```

Quality gates:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov
uv run bandit -c pyproject.toml -r src
```

## 10. Docker quick start

```bash
docker compose up --build            # API on http://localhost:8000, PostgreSQL on 5432
curl localhost:8000/health/ready
docker compose down -v               # stop and remove the volume
```

The image is a multi-stage build (uv-resolved dependencies, slim runtime,
non-root user, health check).

## 11. API examples

Interactive documentation at `/docs` and `/redoc`. Example request bodies live
in [`examples/`](examples/).

Create an account:

```bash
curl -s -X POST localhost:8000/api/v1/accounts -H 'Content-Type: application/json' \
  -d @examples/create_account.json
```

Post a balanced journal entry (the `Idempotency-Key` makes retries safe):

```bash
curl -s -X POST localhost:8000/api/v1/journal-entries \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: dep-demo-0001' \
  -d '{
    "reference": "DEP-DEMO-0001",
    "description": "Synthetic deposit",
    "booking_date": "2026-03-29",
    "postings": [
      {"account_id": "<settlement-asset-id>",    "direction": "DEBIT",  "amount": "1000.00", "currency": "GBP"},
      {"account_id": "<customer-liability-id>",  "direction": "CREDIT", "amount": "1000.00", "currency": "GBP"}
    ]
  }'
```

An unbalanced entry (`999.99` vs `1000.00`) is rejected with
`422 UNBALANCED_JOURNAL`. Transfers (`POST /api/v1/transfers`), balances
(`GET /api/v1/accounts/{id}/balance`), the trial balance
(`GET /api/v1/reconciliation/trial-balance?currency=GBP`) and reversals
(`POST /api/v1/journal-entries/{id}/reverse`) follow the same envelope.

## 12. Testing

The strategy is to test each ledger control at the layer that owns it, and
to test the database-backed controls against a **real PostgreSQL** so that
row locks and unique-constraint races behave exactly as in production.
Locally an embedded PostgreSQL starts automatically; CI uses a service
container.

```bash
uv run pytest                 # whole suite, a few seconds
uv run pytest tests/unit      # pure domain tests, no database
uv run pytest --cov           # coverage report (CI enforces a floor of 85%)
```

| Suite               | Highlights                                                                                  |
|---------------------|---------------------------------------------------------------------------------------------|
| `tests/unit`        | Money precision and float rejection, normal-balance math, balancing rule, immutability, reversal construction, transfer translation, config masking |
| `tests/integration` | Rollback after a simulated failure mid-transaction, idempotency replay/conflict and an 8-thread same-key race, 12 racing transfers never overdrawing, opposite-direction transfers without deadlock, reconciliation |
| `tests/property`    | Hypothesis: every generated balanced entry posts balanced and every perturbation is rejected; transfer + reversal restores balances despite unrelated activity; replays never increase the posting count |

## 13. Design decisions

* **Transfers require accounts with the same normal balance.** "A→B" means A
  decreases and B increases; mixed types cannot balance as two legs, so a
  deposit from a settlement asset to a customer is booked as an explicit
  journal entry rather than guessed.
* **Available funds are domain-aware.** Customer LIABILITY accounts cannot go
  negative by default; ledger/control accounts can. Overridable per account.
* **Single-currency entries.** FX would need position accounts and rates.
* **In-process domain events** with a documented
  [transactional outbox](docs/OUTBOX.md) path instead of a broker for show.

## 14. Limitations

These are conscious scope decisions for an educational v1, not oversights.
The project is **not** production-ready for a regulated banking deployment
and does not claim to be.

* **Authentication and authorisation are intentionally out of scope.** The
  service is designed to sit behind an authenticating gateway.
* **Single PostgreSQL node.** No sharding, read replicas or multi-region
  consistency. Hot accounts serialise on row locks, so per-account throughput
  is bounded by lock hold time.
* **No distributed event platform.** Domain events are dispatched in-process;
  the transactional outbox design in `docs/OUTBOX.md` is the documented next step.
* **No balance snapshot optimisation.** Balances are aggregated from postings on
  every call, which is correct by construction but grows with volume.
* **No idempotency expiry policy.** Records are kept indefinitely; a retention
  job is documented, not implemented.
* No FX, interest, pricing engine, holds/authorisations or statement generation.
* The ISO 20022-inspired adapter is a teaching simplification, not a
  standards implementation.

## 15. Disclaimer

This project is an independent educational implementation using synthetic
data. It is not affiliated with, derived from, or representative of any
production banking system. All account numbers, names and amounts are
fictional. Do not use it to process real financial or personal data.

Licensed under the [MIT License](LICENSE).
