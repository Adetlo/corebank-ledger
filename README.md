# CoreBank Ledger

An educational double-entry ledger service written in Python 3.12.

> **Disclaimer.** This project is an independent educational implementation
> using synthetic data and generic banking concepts. It is not affiliated
> with, derived from, or representative of any production banking system.

## Goal

Build a small but complete core ledger: every movement of value is recorded as
a balanced journal entry (`SUM(debits) == SUM(credits)`), postings are
immutable once posted, and account balances are derived from postings rather
than stored in a `balance` column.

## Status

Early development. The current focus is the framework-free domain model:

* `Money`: `Decimal`-based amounts with per-currency minor units, floats rejected
* `Account`: chart-of-accounts types and debit/credit normal-balance rules
* `JournalEntry` / `Posting`: the double-entry core and its balancing invariant

Persistence (PostgreSQL) and an HTTP API will follow once the domain rules are
settled and tested.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check . && ruff format --check .
mypy
pytest
```

## License

MIT, see [LICENSE](LICENSE).
