# Ledger Invariants

These are the rules the system is built around. Each lists **where** it is
enforced and **which tests** prove it. "Defence in depth" means a rule is
checked in the domain, re-checked in the application transaction, and
reinforced by the database where feasible.

## Invariant 1: Debits equal credits

For every effective journal entry (status `POSTED` or `REVERSED`):

```
SUM(postings.amount WHERE direction = DEBIT) == SUM(postings.amount WHERE direction = CREDIT)
```

within a single currency. A journal entry also needs at least two postings,
at least one on each side, and only positive amounts (sign is expressed by
the direction, never by a negative number).

| Layer       | Enforcement                                                                     |
|-------------|---------------------------------------------------------------------------------|
| Domain      | `validate_balanced()` in `domain/ledger.py`; `JournalEntry.post()` calls it      |
| Application | `post_entry()` can only persist after `post()` succeeded                        |
| Database    | `trg_postings_balanced` / `trg_journal_entries_balanced`: deferred constraint triggers verify the sums at `COMMIT`; `ck_postings_amount_positive` |
| API         | pydantic requires ≥ 2 postings and positive string amounts (convenience only)   |

Tests: `tests/unit/test_ledger.py`, `tests/property/test_ledger_properties.py`,
`tests/integration/test_atomicity.py::TestDatabaseLevelGuards`,
`tests/api/test_journal_api.py::test_unbalanced_entry_rejected`.

## Invariant 2: Posted entries are immutable

Once posted, a posting's amount, account and direction cannot change, and
the entry cannot be deleted. The only permitted change to a posted entry is
`status POSTED → REVERSED` together with setting `reversed_by`, exactly once.

| Layer       | Enforcement                                                                 |
|-------------|-----------------------------------------------------------------------------|
| Domain      | `Posting` is frozen; `JournalEntry` raises `IMMUTABLE_POSTING` after posting |
| Application | no service method edits postings; corrections go through `ReversalService`  |
| Database    | `trg_postings_immutable` (blocks UPDATE/DELETE), `trg_journal_entries_immutable` |
| API         | no PUT/PATCH/DELETE endpoints exist for entries or postings                  |

Tests: `tests/unit/test_ledger.py::TestJournalLifecycle`,
`tests/integration/test_atomicity.py::TestDatabaseLevelGuards`.

## Invariant 3: A transaction posts atomically

Journal row, posting rows, audit events and the idempotency record are
written in **one database transaction**. If any step fails, nothing is kept:
there is never a partially posted entry.

| Layer       | Enforcement                                                                |
|-------------|----------------------------------------------------------------------------|
| Application | `UnitOfWork`: leaving the block without `commit()` rolls back              |
| Database    | PostgreSQL transaction semantics; deferred trigger runs inside the commit  |

Tests: `tests/integration/test_atomicity.py` (simulated failure after postings
are flushed; domain rejection; missing commit; unbalanced raw rows rejected
at commit).

## Invariant 4: Idempotent retries cannot duplicate economic events

Same `Idempotency-Key` + same payload → the original result, no new postings.
Same key + different payload → `409 IDEMPOTENCY_CONFLICT`. Concurrent
duplicates post exactly once.

| Layer       | Enforcement                                                                  |
|-------------|------------------------------------------------------------------------------|
| Application | `IdempotencyGuard` (lookup before, remember in the same transaction)         |
| Database    | `UNIQUE (scope, idempotency_key)`; loser of a race rolls back and replays    |
| API         | `Idempotency-Key` header required on financial mutations (`400` otherwise)  |

Tests: `tests/integration/test_idempotency_integration.py` (including an
8-thread race), `tests/property/test_reversal_and_idempotency_properties.py`,
`tests/api/test_journal_api.py::test_idempotency_header_behaviour`.

## Invariant 5: Reversals preserve history

A reversal is a **new** entry with opposite postings, linked both ways
(`reversal_of` on the reversal, `reversed_by` on the original). The original's
postings are untouched and still count towards balances; the reversal offsets
them. An entry can be reversed at most once; a reversal can itself be reversed
(creating a third entry).

| Layer       | Enforcement                                                               |
|-------------|---------------------------------------------------------------------------|
| Domain      | `JournalEntry.build_reversal()`, `mark_reversed()` (`JOURNAL_ALREADY_REVERSED`) |
| Application | original row locked `FOR UPDATE`; guarded `UPDATE ... WHERE reversed_by IS NULL` |
| Database    | `UNIQUE(reversal_of)`, `UNIQUE(reversed_by)`, trigger forbids un-reversing |

Tests: `tests/unit/test_ledger.py::TestReversal`,
`tests/integration/test_reversal_service.py`,
`tests/property/...::test_transfer_then_reversal_restores_balances`.

## Invariant 6: Balances are derived from postings

There is no stored balance. Every balance is `SUM` over effective postings,
optionally as of a booking date.

```
balance(DEBIT-normal account)  = debit_total  - credit_total   (ASSET, EXPENSE)
balance(CREDIT-normal account) = credit_total - debit_total    (LIABILITY, EQUITY, INCOME)
```

A positive balance means the account holds its natural kind of value. A
customer deposit account is a bank LIABILITY: crediting it increases what the
bank owes the customer; debiting it (a withdrawal, a fee) decreases it.

Tests: `tests/unit/test_accounts.py`, `tests/integration/test_account_service.py`,
`tests/integration/test_reconciliation_service.py`.

## Supporting rules

### Transfers

"Transfer from A to B" means A's balance decreases and B's increases, each in
its natural sign. Posting directions follow from the normal balances:

| Source → Destination        | Postings                             |
|-----------------------------|--------------------------------------|
| LIABILITY → LIABILITY       | DEBIT source, CREDIT destination     |
| ASSET → ASSET               | CREDIT source, DEBIT destination     |
| LIABILITY → INCOME (fee)    | DEBIT customer, CREDIT income        |
| ASSET → LIABILITY (deposit) | **not a transfer** → `INVALID_TRANSFER`; book a journal entry |

Mixed normal balances cannot produce a balanced two-leg entry, so the
service refuses rather than guessing.

### Available funds (simplified)

Accounts carry `allow_negative_balance`. Default: `false` for LIABILITY
(customer deposit) accounts, `true` for ledger/control accounts (assets,
income, expense, equity, suspense), overridable at creation. Any entry that
would take a non-overdraft account below zero is rejected with
`INSUFFICIENT_FUNDS`, including reversals. Balances are read under the row
locks of the posting transaction so concurrent spends cannot both pass.

This is a deliberate simplification: real products have overdraft limits,
holds, pending authorisations and value-dated availability.

### Account lifecycle

`ACTIVE ⇄ FROZEN → CLOSED`. Frozen and closed accounts reject postings
(`ACCOUNT_FROZEN`, `ACCOUNT_CLOSED`). Closing requires a zero balance
(`ACCOUNT_NOT_EMPTY`). Closed is terminal.

### Single-currency entries

All postings in an entry share one currency and every account in it must be
denominated in that currency (`CURRENCY_MISMATCH`). Cross-currency movement
would require FX positions and is out of scope.

## Concurrency model and its limits

* Writers lock affected account rows in ascending id order
  (`SELECT ... FOR UPDATE`), which serialises conflicting entries and
  prevents deadlocks between entries touching the same accounts.
* The journal row is locked during reversal.
* Account status changes use optimistic versioning.
* Default `READ COMMITTED` isolation is sufficient given the explicit locks.

Tested in `tests/integration/test_concurrency.py` (12 racing transfers
draining one account: exactly 5 succeed; opposite-direction transfers do not
deadlock).

**Not solved here:** multi-node or multi-region consistency, lock-free high
throughput on hot accounts, cross-service sagas, exactly-once delivery to
downstream systems. See `docs/OUTBOX.md` for the next step.
