# History reconstruction

This repository was originally developed over an extended period beginning in 2024 and was later
consolidated and published to GitHub. The Git history was reconstructed from the final project
structure and known development phases. Historical commit dates represent approximate development
phases rather than forensic original commit timestamps.

## Reconstructed phases

| Phase | Approximate period | What it added |
|---|---|---|
| Project structure and domain model | Jan–Feb 2024 | Licence, manifest, package skeleton, domain exceptions, `Money`, accounts and normal-balance rules, journal entries and postings with the balancing invariant, transfers as journal entries, domain events |
| Persistence | Mar 2024 | Settings, SQLAlchemy engine and ORM models, account/journal/audit repositories, unit of work |
| Application services and first unit tests | Apr 2024 | Account service, request context, journal query service; unit tests for money, accounts, ledger and transactions |
| Idempotency and reversals | Jan 2025 | Idempotency repository and guard, journal posting engine, reversal service, idempotency unit test |
| Reconciliation and HTTP API | Apr–May 2025 | Reconciliation repository and service, transfer service, pydantic schemas, FastAPI dependencies, presenters and routes |
| Error handling and validation | Jun 2025 | Error envelope, correlation-id and request-size middleware, structured logging, application factory, ISO 20022-inspired payment adapter |
| Test expansion | Sep 2025 | Shared PostgreSQL fixtures, integration tests (atomicity, idempotency, concurrency, services), Hypothesis property tests |
| Containerisation and CI | Nov 2025 | Dockerfile, Docker Compose, `.env.example`, GitHub Actions workflow (quality, security audit, image build) |
| Documentation | Mar 2026 | Architecture, data model, ledger invariants and outbox documents; expanded README; first example payload |
| Release hardening | Sep–Oct 2026 | Demo and seed scripts, HTTP API test suites, security considerations |
| Publication | 13–14 Oct 2026 | Alembic migrations and container entrypoint, ADRs, API reference, dated example payloads, community health files, final README, refreshed CI with `uv.lock` |

## What is and is not authentic

* **File contents are authentic.** Every source, test, configuration and documentation file is
  committed at its published state. Source and test files were never hand-edited to produce
  historical versions.
* **Commit dates, messages and grouping are reconstructed.** They approximate the order in which
  the components were developed; they are not the original timestamps.
* **Intermediate versions exist only for configuration and documentation files**: `pyproject.toml`
  (five earlier versions with a growing dependency list), `README.md` (two earlier versions),
  `.github/workflows/ci.yml` (two earlier versions using `actions/checkout@v4`,
  `astral-sh/setup-uv@v5`, `actions/upload-artifact@v4`, `docker/setup-buildx-action@v3`,
  `docker/build-push-action@v6` and `uv sync` without `--frozen`) and `Dockerfile` (one earlier
  version without the lock file, migrations or entrypoint). The final versions are the published
  files.
* **The repository was published on GitHub in October 2026.**

### Known anachronisms

* Several test modules and schema examples use `2026-10-13` / `2026-10-14` as fixture dates although
  they are committed in earlier phases: `src/corebank/schemas/journal.py`,
  `src/corebank/schemas/transfers.py`, `src/corebank/integrations/payment_messages.py`,
  `tests/helpers.py`, `tests/unit/test_ledger.py`, `tests/unit/test_transactions.py`,
  `tests/unit/test_payment_messages.py`, `tests/integration/conftest.py`,
  `tests/integration/test_atomicity.py`, `tests/api/test_journal_api.py` and
  `tests/api/test_transfers_payments_api.py`.
* `LICENSE` is committed in January 2024 with the copyright year 2024 and updated to 2026 (the publication year) in the October 2026 community-files commit.
* Because files are committed at their final content, some modules reference components that land
  in a later phase: `infrastructure/models.py` and `domain/ledger.py` mention the Alembic triggers,
  `application/unit_of_work.py` imports the repository package aggregator (added with the
  reconciliation repository), `api/routes/payments.py` imports the payment adapter (added in the
  error-handling phase), `docs/DATA_MODEL.md` and `examples/README.md` reference the migration and
  example files published in October 2026, and `tests/conftest.py` runs the Alembic migrations that
  are committed in the publication phase.
* The final `pyproject.toml` dependency lower bounds (for example `fastapi>=0.115`,
  `pydantic>=2.8`) reflect the published manifest; earlier reconstructed versions use bounds that
  were current at their commit dates.
* ADR acceptance dates (`2026-10-13`) and the migration `Create Date` reflect when those documents
  were written up for publication, not when the underlying decisions were taken.
* The `uv.lock` file resolves package versions released in 2026 and is therefore committed in the
  publication phase together with the switch to `uv sync --frozen`.

## Pre-reconstruction history

The history as first published consisted of 11 commits dated 2026-10-13 (the consolidation and
publication commits). That pre-reconstruction history is preserved in an archive branch/tag in the
owner's repository and is not part of the reconstructed main branch.
