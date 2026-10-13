from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from corebank.application.account_service import AccountService
from corebank.application.transfer_service import TransferService
from corebank.domain.events import TransferCompleted
from corebank.domain.exceptions import (
    AccountNotFoundError,
    InsufficientFundsError,
    InvalidTransferError,
    JournalNotFoundError,
    MissingIdempotencyKeyError,
)
from corebank.domain.ledger import Direction, JournalStatus
from corebank.domain.money import Money
from corebank.domain.transactions import TransferCommand
from corebank.infrastructure.repositories.audit import AuditEventType
from tests.integration.conftest import TODAY


def cmd(source, destination, amount: str = "250.00", reference: str = "TRF-1") -> TransferCommand:  # type: ignore[no-untyped-def]
    return TransferCommand(source.id, destination.id, Money.of(amount, "GBP"), reference, TODAY)


def test_transfer_between_customers(uow_factory, ctx, ledger, fund, dispatcher) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "1000.00")
    service = TransferService(uow_factory())
    result = service.transfer(cmd(ledger.customer_a, ledger.customer_b), ctx, idempotency_key="t1")
    journal = result.journal
    assert journal.status is JournalStatus.POSTED and journal.metadata["kind"] == "TRANSFER"
    by_account = {p.account_id: p for p in journal.postings}
    assert by_account[ledger.customer_a.id].direction is Direction.DEBIT
    assert by_account[ledger.customer_b.id].direction is Direction.CREDIT
    accounts = AccountService(uow_factory())
    assert accounts.get_balance(ledger.customer_a.id).balance.amount == Decimal("750.00")
    assert accounts.get_balance(ledger.customer_b.id).balance.amount == Decimal("250.00")
    assert any(
        isinstance(e, TransferCompleted) and e.journal_entry_id == journal.id
        for e in dispatcher.events
    )
    with uow_factory() as uow:
        events = uow.audit.list_for_entity(journal.id)
    assert AuditEventType.TRANSFER_CREATED in {e.event_type for e in events}
    assert service.get_transfer(journal.id).id == journal.id


def test_transfer_replay(uow_factory, ctx, ledger, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "100.00")
    service = TransferService(uow_factory())
    first = service.transfer(
        cmd(ledger.customer_a, ledger.customer_b, "40.00"), ctx, idempotency_key="t2"
    )
    again = service.transfer(
        cmd(ledger.customer_a, ledger.customer_b, "40.00"), ctx, idempotency_key="t2"
    )
    assert again.replayed and again.journal.id == first.journal.id
    assert AccountService(uow_factory()).get_balance(
        ledger.customer_a.id
    ).balance.amount == Decimal("60.00")


def test_insufficient_funds(uow_factory, ctx, ledger, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "100.00")
    service = TransferService(uow_factory())
    with pytest.raises(InsufficientFundsError):
        service.transfer(
            cmd(ledger.customer_a, ledger.customer_b, "100.01"), ctx, idempotency_key="t3"
        )
    assert AccountService(uow_factory()).get_balance(
        ledger.customer_a.id
    ).balance.amount == Decimal("100.00")


def test_transfer_requires_matching_normal_balances(uow_factory, ctx, ledger) -> None:  # type: ignore[no-untyped-def]
    service = TransferService(uow_factory())
    with pytest.raises(InvalidTransferError):
        service.transfer(cmd(ledger.settlement, ledger.customer_a), ctx, idempotency_key="t4")


def test_transfer_unknown_account_and_missing_key(uow_factory, ctx, ledger) -> None:  # type: ignore[no-untyped-def]
    service = TransferService(uow_factory())
    with pytest.raises(AccountNotFoundError):
        service.transfer(
            TransferCommand(ledger.customer_a.id, uuid4(), Money.of("1", "GBP"), "X", TODAY),
            ctx,
            idempotency_key="t5",
        )
    with pytest.raises(MissingIdempotencyKeyError):
        service.transfer(cmd(ledger.customer_a, ledger.customer_b), ctx, idempotency_key=None)
    with pytest.raises(JournalNotFoundError):
        service.get_transfer(uuid4())


def test_get_transfer_rejects_non_transfer_journal(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    result = post(
        [
            (ledger.settlement.id, Direction.DEBIT, "1.00"),
            (ledger.customer_a.id, Direction.CREDIT, "1.00"),
        ]
    )
    with pytest.raises(JournalNotFoundError):
        TransferService(uow_factory()).get_transfer(result.journal.id)
