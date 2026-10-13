# ADR 0001: Use `Decimal` (never binary floating point) for money

**Status:** Accepted · **Date:** 2026-10-13

## Context

Binary floating point cannot represent most decimal fractions exactly:
`0.1 + 0.2 == 0.30000000000000004`. Accumulating thousands of postings with
`float` produces rounding drift that silently breaks `SUM(debits) == SUM(credits)`.

## Decision

* All amounts are `decimal.Decimal`, wrapped in an immutable `Money` value
  object (`src/corebank/domain/money.py`).
* `Money` rejects `float` inputs outright and rejects amounts with more
  precision than the currency's minor unit (GBP 2 dp, JPY 0 dp) instead of
  rounding. Rounding is a business decision made explicitly by callers.
* The database column type is `NUMERIC(19, 4)`; the API serialises amounts as
  JSON **strings** (`"1000.00"`) so no client is tempted to parse them as floats.

## Consequences

* Slightly more verbose arithmetic and explicit currency handling.
* Mixed-currency arithmetic is a hard error (`CURRENCY_MISMATCH`).
* Clients must send amounts as strings; a JSON float is rejected with
  `INVALID_AMOUNT`.
