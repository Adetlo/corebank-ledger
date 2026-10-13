# Migrations

Alembic migrations for the ledger schema. The database URL is taken from the
`DATABASE_URL` environment variable (via `corebank.config.Settings`).

```bash
uv run alembic upgrade head          # apply
uv run alembic downgrade base        # roll back everything
uv run alembic revision -m "..."     # new revision (hand-written, reviewed)
```

Triggers that reinforce ledger invariants are defined in
`versions/0001_initial_ledger_schema.py`; see `docs/DATA_MODEL.md`.
