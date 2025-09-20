from __future__ import annotations

from datetime import date
from decimal import Decimal

from corebank.application.account_service import AccountService, CreateAccountCommand
from corebank.application.reconciliation_service import ReconciliationService
from corebank.domain.accounts import AccountType
from corebank.domain.ledger import Direction


def test_trial_balance_balances_and_lists_every_account(uow_factory, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "1000.00")
    post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "250.00"),
            (ledger.customer_b.id, Direction.CREDIT, "250.00"),
        ],
        reference="T",
    )
    post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "5.00"),
            (ledger.fee_income.id, Direction.CREDIT, "5.00"),
        ],
        reference="F",
    )
    tb = ReconciliationService(uow_factory()).trial_balance(currency="gbp")
    assert tb.currency == "GBP" and tb.balanced and tb.difference.is_zero
    assert tb.total_debits.amount == Decimal("1255.00") == tb.total_credits.amount
    assert len(tb.lines) == 6  # includes accounts with no postings
    lines = {line.account_id: line for line in tb.lines}
    assert lines[ledger.customer_a.id].net_balance.amount == Decimal("745.00")
    assert lines[ledger.customer_a.id].debit_total.amount == Decimal("255.00")
    assert lines[ledger.settlement.id].net_balance.amount == Decimal("1000.00")
    assert lines[ledger.expense.id].net_balance.is_zero


def test_trial_balance_as_of_date(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    post(
        [
            (ledger.settlement.id, Direction.DEBIT, "10.00"),
            (ledger.customer_a.id, Direction.CREDIT, "10.00"),
        ],
        booking_date=date(2026, 1, 1),
        reference="A",
    )
    post(
        [
            (ledger.settlement.id, Direction.DEBIT, "20.00"),
            (ledger.customer_a.id, Direction.CREDIT, "20.00"),
        ],
        booking_date=date(2026, 3, 1),
        reference="B",
    )
    service = ReconciliationService(uow_factory())
    assert service.trial_balance(
        currency="GBP", as_of_date=date(2026, 2, 1)
    ).total_debits.amount == Decimal("10.00")
    assert service.trial_balance(currency="GBP").total_debits.amount == Decimal("30.00")
    assert service.trial_balance(currency="USD").total_debits.is_zero


def test_ledger_check_across_currencies(uow_factory, ctx, ledger, post) -> None:  # type: ignore[no-untyped-def]
    accounts = AccountService(uow_factory())
    yen_asset = accounts.create_account(
        CreateAccountCommand("JPY Nostro", AccountType.ASSET, "JPY"), ctx
    )
    yen_customer = accounts.create_account(
        CreateAccountCommand("JPY Customer", AccountType.LIABILITY, "JPY"), ctx
    )
    post(
        [
            (ledger.settlement.id, Direction.DEBIT, "10.00"),
            (ledger.customer_a.id, Direction.CREDIT, "10.00"),
        ]
    )
    post(
        [(yen_asset.id, Direction.DEBIT, "500"), (yen_customer.id, Direction.CREDIT, "500")],
        currency="JPY",
        reference="Y",
    )
    check = ReconciliationService(uow_factory()).ledger_check()
    assert check.balanced and check.unbalanced_journal_ids == []
    by_currency = {c.currency: c for c in check.currencies}
    assert set(by_currency) == {"GBP", "JPY"}
    assert by_currency["JPY"].total_debits.as_string() == "500"
    assert by_currency["GBP"].posting_count == 2
    assert (
        ReconciliationService(uow_factory()).ledger_check(as_of_date=date(2020, 1, 1)).currencies
        == []
    )


def test_empty_ledger_is_balanced(uow_factory, db) -> None:  # type: ignore[no-untyped-def]
    service = ReconciliationService(uow_factory())
    tb = service.trial_balance(currency="GBP")
    assert tb.balanced and tb.lines == [] and tb.total_debits.is_zero
    assert service.ledger_check().balanced
