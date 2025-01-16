"""Journal posting engine: the single code path that creates postings.

Every financial mutation (journal post, transfer, reversal) ends up in
:func:`post_entry`, inside one database transaction opened by the caller:

1. lock the affected account rows in sorted order (``SELECT ... FOR UPDATE``)
2. verify each account is active and in the journal's currency
3. prove the invariant ``SUM(debits) == SUM(credits)`` (``JournalEntry.post``)
4. enforce available-funds rules for accounts that disallow negative balances
5. persist journal + postings, append audit events, buffer domain events

If anything raises, the caller's unit of work rolls back and nothing is kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from corebank.application.account_service import balance_for
from corebank.application.context import RequestContext
from corebank.application.idempotency import IdempotencyGuard, Replay
from corebank.domain.accounts import Account, compute_balance
from corebank.domain.events import JournalPosted
from corebank.domain.exceptions import (
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    JournalNotFoundError,
    MissingIdempotencyKeyError,
)
from corebank.domain.ledger import BalanceCheck, Direction, JournalEntry, Posting
from corebank.domain.money import Money, sum_money
from corebank.infrastructure.repositories.audit import AuditEvent, AuditEventType

if TYPE_CHECKING:
    from corebank.application.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class PostingLine:
    account_id: UUID
    direction: Direction
    amount: Decimal | str | int
    currency: str


@dataclass(frozen=True, slots=True)
class PostJournalCommand:
    reference: str
    description: str
    booking_date: date
    postings: list[PostingLine]
    value_date: date | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "description": self.description,
            "booking_date": self.booking_date.isoformat(),
            "value_date": (self.value_date or self.booking_date).isoformat(),
            "metadata": self.metadata,
            "postings": [
                {
                    "account_id": str(p.account_id),
                    "direction": str(p.direction),
                    "amount": str(p.amount),
                    "currency": p.currency,
                }
                for p in self.postings
            ],
        }


@dataclass(frozen=True, slots=True)
class PostResult:
    journal: JournalEntry
    replayed: bool = False
    check: BalanceCheck | None = None


def lock_accounts(uow: UnitOfWork, account_ids: set[UUID]) -> dict[UUID, Account]:
    accounts = uow.accounts.get_many_for_update(account_ids)
    missing = account_ids - set(accounts)
    if missing:
        raise AccountNotFoundError(account_id=str(sorted(missing)[0]))
    return accounts


def post_entry(uow: UnitOfWork, entry: JournalEntry, ctx: RequestContext) -> BalanceCheck:
    """Post ``entry`` inside the caller's open transaction (see module docs)."""
    accounts = lock_accounts(uow, {p.account_id for p in entry.postings})
    currency = entry.postings[0].currency if entry.postings else entry.currency
    for account in accounts.values():
        account.ensure_can_post()
        if account.currency != currency:
            raise CurrencyMismatchError(
                f"Account {account.account_number} is a {account.currency} account; "
                f"the journal entry is in {currency}.",
                account_id=str(account.id),
                account_currency=account.currency,
                journal_currency=currency,
            )

    check = entry.post()  # raises UnbalancedJournalError; this is THE invariant
    _enforce_available_funds(uow, entry, accounts)

    uow.journals.add(entry)
    uow.audit.add(
        AuditEvent(
            entity_type="journal_entry",
            entity_id=entry.id,
            event_type=AuditEventType.JOURNAL_CREATED,
            correlation_id=ctx.correlation_id,
            actor=ctx.actor,
            metadata={"reference": entry.reference, "posting_count": len(entry.postings)},
        )
    )
    uow.audit.add(
        AuditEvent(
            entity_type="journal_entry",
            entity_id=entry.id,
            event_type=AuditEventType.JOURNAL_POSTED,
            correlation_id=ctx.correlation_id,
            actor=ctx.actor,
            metadata={
                "reference": entry.reference,
                "currency": check.currency,
                "total_debits": check.total_debits.as_string(),
                "total_credits": check.total_credits.as_string(),
                "reversal_of": str(entry.reversal_of) if entry.reversal_of else None,
            },
        )
    )
    uow.add_event(
        JournalPosted(
            correlation_id=ctx.correlation_id,
            journal_entry_id=entry.id,
            reference=entry.reference,
            currency=check.currency,
            total_debits=check.total_debits.amount,
            posting_count=len(entry.postings),
        )
    )
    return check


def _enforce_available_funds(
    uow: UnitOfWork, entry: JournalEntry, accounts: dict[UUID, Account]
) -> None:
    """Reject the entry if it would overdraw an account that forbids it.

    Balances are read under the row locks taken by :func:`lock_accounts`, so
    two concurrent entries cannot both pass this check against the same funds.
    """
    for account in accounts.values():
        if account.allow_negative_balance:
            continue
        current = balance_for(uow, account).balance
        legs = [p for p in entry.postings if p.account_id == account.id]
        debits = sum_money(
            [p.money for p in legs if p.direction is Direction.DEBIT], account.currency
        )
        credits = sum_money(
            [p.money for p in legs if p.direction is Direction.CREDIT], account.currency
        )
        delta = compute_balance(account.normal_balance, debits, credits)
        projected = current + delta
        if projected.is_negative:
            raise InsufficientFundsError(
                f"Account {account.account_number} has {current.as_string()} "
                f"{account.currency} available; the entry requires "
                f"{(-delta).as_string()} {account.currency}.",
                account_id=str(account.id),
                available=current.as_string(),
                required=(-delta).as_string(),
                currency=account.currency,
            )


class PostingService:
    """Use case: post a journal entry supplied by an API client."""

    def __init__(self, uow: UnitOfWork, *, require_idempotency_key: bool = True) -> None:
        self._uow = uow
        self._require_key = require_idempotency_key

    def post_journal(
        self,
        command: PostJournalCommand,
        ctx: RequestContext,
        *,
        idempotency_key: str | None,
    ) -> PostResult:
        if self._require_key and not idempotency_key:
            raise MissingIdempotencyKeyError()
        guard = IdempotencyGuard("journal_entries.post", idempotency_key, command.fingerprint())
        try:
            return self._execute(command, ctx, guard)
        except IntegrityError as exc:
            # A concurrent request with the same key committed first.
            if "uq_idempotency_scope_key" not in str(exc.orig):
                raise
            replay = self._replay(guard, ctx)
            if replay is None:
                raise
            return replay

    def _execute(
        self, command: PostJournalCommand, ctx: RequestContext, guard: IdempotencyGuard
    ) -> PostResult:
        with self._uow as uow:
            replay = guard.lookup(uow.idempotency)
            if replay is not None:
                return self._load_replay(uow, replay, ctx)
            entry = JournalEntry(
                reference=command.reference,
                description=command.description,
                booking_date=command.booking_date,
                value_date=command.value_date,
                postings=[
                    Posting(
                        account_id=line.account_id,
                        direction=Direction(line.direction),
                        money=Money.of(line.amount, line.currency),
                    )
                    for line in command.postings
                ],
                idempotency_key=guard.key,
                metadata=dict(command.metadata),
            )
            check = post_entry(uow, entry, ctx)
            guard.remember(
                uow.idempotency,
                resource_id=entry.id,
                response_status=201,
                response_body={"resource_type": "journal_entry", "resource_id": str(entry.id)},
            )
            uow.commit()
        return PostResult(journal=entry, replayed=False, check=check)

    def _replay(self, guard: IdempotencyGuard, ctx: RequestContext) -> PostResult | None:
        with self._uow as uow:
            replay = guard.lookup(uow.idempotency)
            if replay is None:
                return None
            return self._load_replay(uow, replay, ctx)

    def _load_replay(self, uow: UnitOfWork, replay: Replay, ctx: RequestContext) -> PostResult:
        if replay.resource_id is None:
            raise JournalNotFoundError()
        journal = uow.journals.get(replay.resource_id)
        if journal is None:
            raise JournalNotFoundError(journal_entry_id=str(replay.resource_id))
        uow.audit.add(
            AuditEvent(
                entity_type="journal_entry",
                entity_id=journal.id,
                event_type=AuditEventType.IDEMPOTENT_REPLAY,
                correlation_id=ctx.correlation_id,
                actor=ctx.actor,
                metadata={"reference": journal.reference},
            )
        )
        uow.commit()
        return PostResult(journal=journal, replayed=True, check=None)
