from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from corebank.application.posting_service import PostingService
from corebank.domain.events import JournalPosted
from corebank.domain.exceptions import (
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    MissingIdempotencyKeyError,
    UnbalancedJournalError,
)
from corebank.domain.ledger import Direction, JournalStatus
from corebank.infrastructure.models import JournalEntryModel, PostingModel
from corebank.infrastructure.repositories.audit import AuditEventType
from tests.integration.conftest import journal_command


def counts(uow_factory):  # type: ignore[no-untyped-def]
    with uow_factory() as uow:
        journals = uow.session.execute(select(func.count(JournalEntryModel.id))).scalar_one()
        postings = uow.session.execute(select(func.count(PostingModel.id))).scalar_one()
    return journals, postings


def test_post_balanced_entry(uow_factory, ledger, post, dispatcher) -> None:  # type: ignore[no-untyped-def]
    result = post(
        [
            (ledger.settlement.id, Direction.DEBIT, "1000.00"),
            (ledger.customer_a.id, Direction.CREDIT, "1000.00"),
        ],
        reference="DEP-DEMO-0001",
    )
    journal = result.journal
    assert journal.status is JournalStatus.POSTED and journal.posted_at is not None
    assert result.check is not None and result.check.balanced
    assert not result.replayed
    with uow_factory() as uow:
        stored = uow.journals.get(journal.id)
        events = uow.audit.list_for_entity(journal.id)
    assert stored is not None and stored.status is JournalStatus.POSTED
    assert len(stored.postings) == 2 and stored.idempotency_key is not None
    assert {p.direction for p in stored.postings} == {Direction.DEBIT, Direction.CREDIT}
    assert [e.event_type for e in events] == [
        AuditEventType.JOURNAL_CREATED,
        AuditEventType.JOURNAL_POSTED,
    ]
    posted = [e for e in dispatcher.events if isinstance(e, JournalPosted)]
    assert posted and posted[-1].journal_entry_id == journal.id


def test_unbalanced_entry_rejected_and_nothing_persisted(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UnbalancedJournalError):
        post(
            [
                (ledger.settlement.id, Direction.DEBIT, "999.99"),
                (ledger.customer_a.id, Direction.CREDIT, "1000.00"),
            ]
        )
    assert counts(uow_factory) == (0, 0)


def test_unknown_account_rejected(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(AccountNotFoundError):
        post([(ledger.settlement.id, Direction.DEBIT, "1.00"), (uuid4(), Direction.CREDIT, "1.00")])
    assert counts(uow_factory) == (0, 0)


def test_currency_must_match_accounts(uow_factory, ctx, ledger, post) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(CurrencyMismatchError):
        post(
            [
                (ledger.settlement.id, Direction.DEBIT, "100"),
                (ledger.customer_a.id, Direction.CREDIT, "100"),
            ],
            currency="JPY",
        )
    assert counts(uow_factory) == (0, 0)


def test_insufficient_funds_on_customer_liability(uow_factory, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "100.00")
    with pytest.raises(InsufficientFundsError) as exc:
        post(
            [
                (ledger.customer_a.id, Direction.DEBIT, "100.01"),
                (ledger.fee_income.id, Direction.CREDIT, "100.01"),
            ]
        )
    assert exc.value.details["available"] == "100.00" and exc.value.details["required"] == "100.01"
    # Exactly the available amount is fine.
    post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "100.00"),
            (ledger.fee_income.id, Direction.CREDIT, "100.00"),
        ]
    )
    assert counts(uow_factory) == (2, 4)


def test_accounts_allowing_negative_balance_can_go_negative(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    # Suspense (LIABILITY, allow_negative_balance=True) can be debited with no funds.
    post(
        [
            (ledger.suspense.id, Direction.DEBIT, "40.00"),
            (ledger.customer_b.id, Direction.CREDIT, "40.00"),
        ]
    )
    with uow_factory() as uow:
        totals = uow.accounts.balance_totals(ledger.suspense.id)
    assert totals.debit_total == Decimal("40.0000") and totals.credit_total == 0


def test_idempotency_key_is_required_by_default(uow_factory, ctx, ledger) -> None:  # type: ignore[no-untyped-def]
    service = PostingService(uow_factory())
    command = journal_command(
        [
            (ledger.settlement.id, Direction.DEBIT, "1.00"),
            (ledger.customer_a.id, Direction.CREDIT, "1.00"),
        ]
    )
    with pytest.raises(MissingIdempotencyKeyError):
        service.post_journal(command, ctx, idempotency_key=None)
    relaxed = PostingService(uow_factory(), require_idempotency_key=False)
    result = relaxed.post_journal(command, ctx, idempotency_key=None)
    assert result.journal.idempotency_key is None


def test_multi_leg_entry(uow_factory, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "100.00")
    result = post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "30.00"),
            (ledger.customer_b.id, Direction.CREDIT, "25.00"),
            (ledger.fee_income.id, Direction.CREDIT, "5.00"),
        ],
        reference="SPLIT-1",
    )
    assert len(result.journal.postings) == 3
    with uow_factory() as uow:
        assert uow.accounts.balance_totals(ledger.customer_b.id).credit_total == Decimal("25")
