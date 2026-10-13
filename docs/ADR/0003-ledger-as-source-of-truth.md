# ADR 0003: Postings are the source of truth; balances are derived

**Status:** Accepted · **Date:** 2026-10-13

## Context

A mutable `balance` column is convenient but introduces a second source of
truth that can drift from the postings through bugs, partial failures or
manual fixes. Drift is the classic cause of unreconcilable ledgers.

## Decision

* No balance column. `GET /accounts/{id}/balance` and the trial balance are
  computed with `SUM(...)` over effective postings (`POSTED` and `REVERSED`
  entries), optionally filtered by `booking_date <= as_of_date`.
* Available-funds checks read the same aggregate under row locks.

## Consequences

* Correctness by construction: a balance can never disagree with the postings.
* Cost grows with posting volume. The documented mitigation is a
  **balance snapshot/projection table** that is explicitly derived state,
  rebuilt from postings and validated against them, never written by hand.
  Indexes on `postings(account_id, journal_entry_id)` and
  `journal_entries(booking_date, status)` keep the v1 query fast.
