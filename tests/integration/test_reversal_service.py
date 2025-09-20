from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from corebank.application.account_service import AccountService
from corebank.application.reversal_service import ReversalService, ReverseJournalCommand
from corebank.domain.events import JournalReversed
from corebank.domain.exceptions import (
    IdempotencyConflictError,
    InsufficientFundsError,
    JournalAlreadyReversedError,
    JournalNotFoundError,
    MissingIdempotencyKeyError,
)
from corebank.domain.ledger import Direction, JournalStatus
from corebank.infrastructure.repositories.audit import AuditEventType


def test_reversal_restores_balances_and_links_entries(
    uow_factory, ctx, ledger, post, fund, dispatcher
) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "100.00")
    fee = post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "5.00"),
            (ledger.fee_income.id, Direction.CREDIT, "5.00"),
        ],
        reference="FEE-1",
    )
    accounts = AccountService(uow_factory())
    assert accounts.get_balance(ledger.customer_a.id).balance.amount == Decimal("95.00")

    service = ReversalService(uow_factory())
    result = service.reverse(
        ReverseJournalCommand(fee.journal.id, reason="waived"), ctx, idempotency_key="rev-1"
    )
    reversal, original = result.reversal, result.original
    assert reversal.reversal_of == original.id and reversal.status is JournalStatus.POSTED
    assert reversal.reference == "REV-FEE-1" and reversal.metadata["reversal_reason"] == "waived"
    assert original.status is JournalStatus.REVERSED and original.reversed_by == reversal.id
    by_account = {p.account_id: p.direction for p in reversal.postings}
    assert by_account[ledger.customer_a.id] is Direction.CREDIT
    assert by_account[ledger.fee_income.id] is Direction.DEBIT
    assert accounts.get_balance(ledger.customer_a.id).balance.amount == Decimal("100.00")
    assert accounts.get_balance(ledger.fee_income.id).balance.is_zero

    with uow_factory() as uow:
        stored_original = uow.journals.get(original.id)
        events = uow.audit.list_for_entity(original.id)
    assert stored_original is not None and stored_original.status is JournalStatus.REVERSED
    assert stored_original.reversed_by == reversal.id
    # Original postings are untouched: history is preserved.
    assert {p.id for p in stored_original.postings} == {p.id for p in fee.journal.postings}
    assert AuditEventType.JOURNAL_REVERSED in {e.event_type for e in events}
    assert any(
        isinstance(e, JournalReversed) and e.reversal_journal_entry_id == reversal.id
        for e in dispatcher.events
    )


def test_cannot_reverse_twice(uow_factory, ctx, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "10.00")
    fee = post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "1.00"),
            (ledger.fee_income.id, Direction.CREDIT, "1.00"),
        ]
    )
    service = ReversalService(uow_factory())
    service.reverse(ReverseJournalCommand(fee.journal.id), ctx, idempotency_key="r1")
    with pytest.raises(JournalAlreadyReversedError):
        service.reverse(ReverseJournalCommand(fee.journal.id), ctx, idempotency_key="r2")
    with uow_factory() as uow:
        assert uow.journals.count_postings() == 6


def test_reversal_is_idempotent(uow_factory, ctx, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "10.00")
    fee = post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "1.00"),
            (ledger.fee_income.id, Direction.CREDIT, "1.00"),
        ]
    )
    service = ReversalService(uow_factory())
    first = service.reverse(ReverseJournalCommand(fee.journal.id), ctx, idempotency_key="same")
    again = service.reverse(ReverseJournalCommand(fee.journal.id), ctx, idempotency_key="same")
    assert (
        again.replayed
        and again.reversal.id == first.reversal.id
        and again.original.id == fee.journal.id
    )
    with pytest.raises(IdempotencyConflictError):
        service.reverse(
            ReverseJournalCommand(fee.journal.id, reason="different"), ctx, idempotency_key="same"
        )


def test_reversing_a_reversal_creates_a_third_entry(uow_factory, ctx, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "10.00")
    fee = post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "1.00"),
            (ledger.fee_income.id, Direction.CREDIT, "1.00"),
        ]
    )
    service = ReversalService(uow_factory())
    rev = service.reverse(ReverseJournalCommand(fee.journal.id), ctx, idempotency_key="a").reversal
    rev2 = service.reverse(ReverseJournalCommand(rev.id), ctx, idempotency_key="b").reversal
    assert rev2.reversal_of == rev.id
    assert AccountService(uow_factory()).get_balance(
        ledger.fee_income.id
    ).balance.amount == Decimal("1.00")


def test_reversal_respects_available_funds(uow_factory, ctx, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    deposit = fund(ledger.customer_a, "10.00")
    post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "10.00"),
            (ledger.fee_income.id, Direction.CREDIT, "10.00"),
        ]
    )
    with pytest.raises(InsufficientFundsError):
        ReversalService(uow_factory()).reverse(
            ReverseJournalCommand(deposit.journal.id), ctx, idempotency_key="x"
        )


def test_reverse_unknown_or_without_key(uow_factory, ctx) -> None:  # type: ignore[no-untyped-def]
    service = ReversalService(uow_factory())
    with pytest.raises(JournalNotFoundError):
        service.reverse(ReverseJournalCommand(uuid4()), ctx, idempotency_key="k")
    with pytest.raises(MissingIdempotencyKeyError):
        service.reverse(ReverseJournalCommand(uuid4()), ctx, idempotency_key=None)
