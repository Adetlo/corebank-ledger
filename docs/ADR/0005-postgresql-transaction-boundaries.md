# ADR 0005: One PostgreSQL transaction per use case, with row locks

**Status:** Accepted · **Date:** 2026-10-13

## Context

A journal entry is a set of rows (entry, postings, audit events, idempotency
record) that must be all-or-nothing. Concurrent entries against the same
account must not double-spend. SQLite was considered for tests but lacks
`SELECT ... FOR UPDATE` and deferred constraint triggers, which would mean
testing a weaker system than the one shipped.

## Decision

* The `UnitOfWork` opens one transaction per use case; leaving the block
  without `commit()` rolls everything back.
* Posting locks the affected account rows with `SELECT ... FOR UPDATE`
  **in ascending id order** (deadlock-free), then reads balances, then writes.
* Default `READ COMMITTED` isolation is sufficient because every write path
  takes the row locks; no reliance on `SERIALIZABLE`.
* Account status changes use optimistic versioning (`version` column) on top.
* A `DEFERRABLE INITIALLY DEFERRED` constraint trigger re-checks
  `SUM(debits) == SUM(credits)` for every effective entry at commit time.
* PostgreSQL only. Tests use an embedded PostgreSQL (`pgserver`) locally and a
  service container in CI.

## Consequences

* Strong single-node guarantees with simple reasoning.
* Hot accounts serialise writes; throughput on one account is bounded by lock
  hold time. Sharding, batching or multi-region consistency are out of scope
  and documented as such.
