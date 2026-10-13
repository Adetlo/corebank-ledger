# Contributing

Thanks for your interest. This is an educational project; contributions that
sharpen the ledger controls, tests or documentation are very welcome.

## Setup

```bash
git clone https://github.com/Adetlo/corebank-ledger.git
cd corebank-ledger
uv sync                       # creates .venv with runtime + dev dependencies
cp .env.example .env          # optional, for running the API locally
```

Requirements: [uv](https://docs.astral.sh/uv/) and Python 3.12 (uv installs it
on demand). Docker is only needed for `docker compose up`.

## Testing

Tests run against a **real PostgreSQL**. Nothing to install: the `pgserver`
wheel starts an embedded PostgreSQL 16 in a temporary directory. To use your
own database instead, set `TEST_DATABASE_URL`.

```bash
uv run pytest                 # whole suite (~5 s)
uv run pytest tests/unit      # pure domain tests, no database
uv run pytest --cov           # with coverage report
```

Test layout:

| Directory            | What it covers                                              |
|----------------------|-------------------------------------------------------------|
| `tests/unit`         | Money, accounts, journal invariants, reversal logic, config |
| `tests/integration`  | Services against PostgreSQL: atomicity, locking, triggers   |
| `tests/property`     | Hypothesis properties: balancing, reversal, idempotency     |
| `tests/api`          | HTTP contract: status codes, error envelope, pagination     |

## Lint, format, types, security

```bash
uv run ruff check .
uv run ruff format .
uv run mypy
uv run bandit -c pyproject.toml -r src
uv export --frozen --no-emit-project --no-hashes --format requirements-txt -o requirements-audit.txt
uv run pip-audit -r requirements-audit.txt --strict
```

CI runs all of the above plus a Docker image build and smoke test.

## Commit style

Conventional Commits, imperative mood, scoped when useful:

```
feat: add idempotent transfer processing
fix(reversal): reject reversal of a FAILED entry
test: cover concurrent transfers against one account
docs: explain balance derivation
```

## Pull request expectations

* Keep the ledger invariants intact (see `docs/LEDGER_INVARIANTS.md`). A change
  that weakens balancing, immutability, atomicity or idempotency needs an ADR.
* Every behaviour change ships with tests. Bug fixes include a regression test.
* New error codes are added to `docs/API.md`.
* Database changes come with an Alembic migration and, where possible, a
  constraint or trigger reinforcing the rule.
* No real data, credentials, hostnames or institution-specific structures.
