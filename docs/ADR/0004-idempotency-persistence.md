# ADR 0004: Persist idempotency state in the ledger database

**Status:** Accepted · **Date:** 2026-10-13

## Context

Network retries are inevitable. A retried `POST /transfers` must not move
money twice. In-memory or cache-based deduplication fails on restarts and
cannot be transactionally consistent with the postings.

## Decision

* Financial mutations (`POST /journal-entries`, `POST /transfers`,
  `POST /journal-entries/{id}/reverse`, `POST /payments/instructions`) require
  an `Idempotency-Key` header (configurable via `REQUIRE_IDEMPOTENCY_KEY`).
* The record (`scope`, `key`, SHA-256 of the canonical payload, resource id,
  response) is inserted **in the same transaction** as the postings.
* Same key + same payload → stored result replayed (`200`, header
  `Idempotent-Replayed: true`, audit `IDEMPOTENT_REPLAY`).
  Same key + different payload → `409 IDEMPOTENCY_CONFLICT`.
* `UNIQUE (scope, idempotency_key)` makes concurrent duplicates safe: the loser
  rolls back and replays the winner's result.
* Failed requests do not consume the key, so a client can fix and retry.

## Consequences

* Retries are safe without client-side bookkeeping beyond generating a UUID.
* Keys are scoped per operation; the same key may be used for a transfer and
  a journal post without interference.
* Records should be expired by a retention job (documented, not implemented).
