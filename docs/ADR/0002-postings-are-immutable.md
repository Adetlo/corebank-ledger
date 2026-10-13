# ADR 0002: Posted journal entries and postings are immutable

**Status:** Accepted · **Date:** 2026-10-13

## Context

An auditable ledger must show what was recorded and when. Editing or deleting
a posting destroys the trail and makes historical balances unreproducible.

## Decision

* `Posting` is a frozen dataclass; `JournalEntry` refuses structural changes
  once POSTED (`IMMUTABLE_POSTING`).
* There is no `PUT`/`PATCH`/`DELETE` for journal entries or postings.
* PostgreSQL triggers (`trg_postings_immutable`, `trg_journal_entries_immutable`)
  block `UPDATE`/`DELETE` on postings and on the core fields of posted
  entries, even for direct SQL access.
* Corrections are made with a **reversal**: a new entry with opposite postings
  linked via `reversal_of` / `reversed_by`. An entry can be reversed once.

## Consequences

* Mistakes stay visible; the trial balance always reconciles to history.
* Storage grows monotonically (acceptable; archival is a future concern).
* Reversals are subject to the same controls as any posting, including
  available-funds checks.
