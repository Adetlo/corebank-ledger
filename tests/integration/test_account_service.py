from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from corebank.application.account_service import AccountService, CreateAccountCommand
from corebank.domain.accounts import AccountStatus, AccountType, NormalBalance
from corebank.domain.events import AccountCreated
from corebank.domain.exceptions import (
    AccountFrozenError,
    AccountNotEmptyError,
    AccountNotFoundError,
    ConcurrencyConflictError,
    UnsupportedCurrencyError,
)
from corebank.domain.ledger import Direction
from corebank.infrastructure.repositories.audit import AuditEventType


def test_create_and_get_account(uow_factory, ctx, dispatcher) -> None:  # type: ignore[no-untyped-def]
    service = AccountService(uow_factory())
    account = service.create_account(
        CreateAccountCommand("Synthetic Customer", AccountType.LIABILITY, "gbp"), ctx
    )
    assert account.account_number.startswith("SYN-")
    assert account.normal_balance is NormalBalance.CREDIT
    assert account.currency == "GBP"
    assert account.allow_negative_balance is False
    fetched = service.get_account(account.id)
    assert fetched == account
    assert any(isinstance(e, AccountCreated) for e in dispatcher.events)
    with uow_factory() as uow:
        events = uow.audit.list_for_entity(account.id)
    assert [e.event_type for e in events] == [AuditEventType.ACCOUNT_CREATED]
    assert events[0].correlation_id == "test-correlation" and events[0].actor == "pytest"


def test_unknown_account(uow_factory) -> None:  # type: ignore[no-untyped-def]
    service = AccountService(uow_factory())
    with pytest.raises(AccountNotFoundError):
        service.get_account(uuid4())
    with pytest.raises(AccountNotFoundError):
        service.get_balance(uuid4())
    with pytest.raises(UnsupportedCurrencyError):
        service.create_account(CreateAccountCommand("x", AccountType.ASSET, "XXX"), ctx=None)  # type: ignore[arg-type]


def test_list_accounts_with_filters_and_pagination(uow_factory, ctx, ledger) -> None:  # type: ignore[no-untyped-def]
    service = AccountService(uow_factory())
    items, total = service.list_accounts(limit=2, offset=0)
    assert total == 6 and len(items) == 2
    items, total = service.list_accounts(limit=10, offset=4)
    assert total == 6 and len(items) == 2
    items, total = service.list_accounts(limit=10, offset=0, account_type=AccountType.LIABILITY)
    assert total == 3 and all(a.account_type is AccountType.LIABILITY for a in items)
    items, total = service.list_accounts(
        limit=10, offset=0, currency="GBP", status=AccountStatus.ACTIVE
    )
    assert total == 6


def test_balance_is_derived_and_date_aware(uow_factory, ctx, ledger, post) -> None:  # type: ignore[no-untyped-def]
    service = AccountService(uow_factory())
    post(
        [
            (ledger.settlement.id, Direction.DEBIT, "100.00"),
            (ledger.customer_a.id, Direction.CREDIT, "100.00"),
        ],
        booking_date=date(2026, 1, 10),
        reference="F1",
    )
    post(
        [
            (ledger.settlement.id, Direction.DEBIT, "50.00"),
            (ledger.customer_a.id, Direction.CREDIT, "50.00"),
        ],
        booking_date=date(2026, 2, 10),
        reference="F2",
    )
    bal = service.get_balance(ledger.customer_a.id)
    assert bal.balance.amount == Decimal("150.00")
    assert bal.credit_total.amount == Decimal("150.00") and bal.debit_total.amount == 0
    assert bal.posting_count == 2
    bal_jan = service.get_balance(ledger.customer_a.id, as_of_date=date(2026, 1, 31))
    assert bal_jan.balance.amount == Decimal("100.00") and bal_jan.as_of_date == date(2026, 1, 31)
    assert service.get_balance(ledger.customer_a.id, as_of_date=date(2025, 12, 31)).balance.is_zero
    assert service.get_balance(ledger.settlement.id).balance.amount == Decimal("150.00")


def test_freeze_blocks_postings_and_close_requires_zero_balance(
    uow_factory, ctx, ledger, post, fund
) -> None:  # type: ignore[no-untyped-def]
    service = AccountService(uow_factory())
    fund(ledger.customer_a, "10.00")
    frozen = service.change_status(ledger.customer_a.id, AccountStatus.FROZEN, ctx)
    assert frozen.status is AccountStatus.FROZEN and frozen.version == 2
    with pytest.raises(AccountFrozenError):
        post(
            [
                (ledger.customer_a.id, Direction.DEBIT, "1.00"),
                (ledger.fee_income.id, Direction.CREDIT, "1.00"),
            ]
        )
    with pytest.raises(AccountNotEmptyError):
        service.change_status(ledger.customer_a.id, AccountStatus.CLOSED, ctx)
    service.change_status(ledger.customer_a.id, AccountStatus.ACTIVE, ctx)
    post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "10.00"),
            (ledger.fee_income.id, Direction.CREDIT, "10.00"),
        ]
    )
    closed = service.change_status(ledger.customer_a.id, AccountStatus.CLOSED, ctx)
    assert closed.status is AccountStatus.CLOSED
    with uow_factory() as uow:
        events = uow.audit.list_for_entity(ledger.customer_a.id)
    assert [e.event_type for e in events].count(AuditEventType.ACCOUNT_STATUS_CHANGED) == 3


def test_optimistic_version_conflict(uow_factory, ledger) -> None:  # type: ignore[no-untyped-def]
    with uow_factory() as uow:
        account = uow.accounts.get(ledger.customer_a.id)
        assert account is not None
        with pytest.raises(ConcurrencyConflictError):
            uow.accounts.save(account, expected_version=99)


def test_get_by_number(uow_factory, ledger) -> None:  # type: ignore[no-untyped-def]
    with uow_factory() as uow:
        found = uow.accounts.get_by_number(ledger.customer_a.account_number)
        assert found is not None and found.id == ledger.customer_a.id
        assert uow.accounts.get_by_number("SYN-0000000000-0") is None
