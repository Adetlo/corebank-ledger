"""ORM <-> domain mapping helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from corebank.domain.accounts import Account, AccountStatus, AccountType
from corebank.domain.ledger import Direction, JournalEntry, JournalStatus, Posting
from corebank.domain.money import Money
from corebank.infrastructure.models import AccountModel, JournalEntryModel, PostingModel


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def account_to_domain(model: AccountModel) -> Account:
    return Account(
        id=model.id,
        account_number=model.account_number,
        account_name=model.account_name,
        account_type=AccountType(model.account_type),
        currency=model.currency,
        status=AccountStatus(model.status),
        allow_negative_balance=model.allow_negative_balance,
        version=model.version,
        created_at=aware(model.created_at),
        updated_at=aware(model.updated_at),
    )


def account_to_model(account: Account) -> AccountModel:
    return AccountModel(
        id=account.id,
        account_number=account.account_number,
        account_name=account.account_name,
        account_type=account.account_type.value,
        currency=account.currency,
        status=account.status.value,
        normal_balance=account.normal_balance.value,
        allow_negative_balance=bool(account.allow_negative_balance),
        version=account.version,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def posting_to_domain(model: PostingModel) -> Posting:
    return Posting(
        id=model.id,
        journal_entry_id=model.journal_entry_id,
        account_id=model.account_id,
        direction=Direction(model.direction),
        money=Money(Decimal(model.amount), model.currency),
        created_at=aware(model.created_at),
    )


def posting_to_model(posting: Posting) -> PostingModel:
    return PostingModel(
        id=posting.id,
        journal_entry_id=posting.journal_entry_id,
        account_id=posting.account_id,
        direction=posting.direction.value,
        amount=posting.money.amount,
        currency=posting.money.currency,
        created_at=posting.created_at,
    )


def journal_to_domain(model: JournalEntryModel) -> JournalEntry:
    return JournalEntry(
        id=model.id,
        reference=model.reference,
        description=model.description,
        booking_date=model.booking_date,
        value_date=model.value_date,
        status=JournalStatus(model.status),
        currency=model.currency,
        idempotency_key=model.idempotency_key,
        metadata=dict(model.metadata_ or {}),
        reversal_of=model.reversal_of,
        reversed_by=model.reversed_by,
        created_at=aware(model.created_at),
        posted_at=aware(model.posted_at) if model.posted_at else None,
        postings=[posting_to_domain(p) for p in model.postings],
    )


def journal_to_model(entry: JournalEntry) -> JournalEntryModel:
    if entry.currency is None:
        raise ValueError("journal entry currency must be set before persisting")
    return JournalEntryModel(
        id=entry.id,
        reference=entry.reference,
        description=entry.description,
        booking_date=entry.booking_date,
        value_date=entry.value_date or entry.booking_date,
        status=entry.status.value,
        currency=entry.currency,
        idempotency_key=entry.idempotency_key,
        metadata_=dict(entry.metadata),
        reversal_of=entry.reversal_of,
        reversed_by=entry.reversed_by,
        created_at=entry.created_at,
        posted_at=entry.posted_at,
        postings=[posting_to_model(p) for p in entry.postings],
    )
