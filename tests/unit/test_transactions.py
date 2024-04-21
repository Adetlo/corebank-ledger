from __future__ import annotations

from datetime import date

import pytest

from corebank.domain.accounts import Account, AccountType
from corebank.domain.exceptions import CurrencyMismatchError, InvalidTransferError
from corebank.domain.ledger import Direction
from corebank.domain.money import Money
from corebank.domain.transactions import TransferCommand, build_transfer_journal

TODAY = date(2026, 10, 13)


def command(
    source: Account, destination: Account, amount: str = "250.00", currency: str = "GBP"
) -> TransferCommand:
    return TransferCommand(
        source_account_id=source.id,
        destination_account_id=destination.id,
        money=Money.of(amount, currency),
        reference="TRF-1",
        booking_date=TODAY,
    )


def directions(entry, source, destination):  # type: ignore[no-untyped-def]
    by_account = {p.account_id: p.direction for p in entry.postings}
    return by_account[source.id], by_account[destination.id]


def test_liability_to_liability_is_debit_source_credit_destination() -> None:
    a = Account("Customer A", AccountType.LIABILITY, "GBP")
    b = Account("Customer B", AccountType.LIABILITY, "GBP")
    entry = build_transfer_journal(command(a, b), a, b, idempotency_key="k")
    assert directions(entry, a, b) == (Direction.DEBIT, Direction.CREDIT)
    assert entry.balance_check().balanced
    assert entry.metadata["kind"] == "TRANSFER"
    assert entry.metadata["source_account_id"] == str(a.id)
    assert entry.idempotency_key == "k"
    assert entry.value_date == TODAY
    assert a.account_number in entry.description


def test_asset_to_asset_is_credit_source_debit_destination() -> None:
    vault = Account("Vault", AccountType.ASSET, "GBP")
    settlement = Account("Settlement", AccountType.ASSET, "GBP")
    entry = build_transfer_journal(command(vault, settlement), vault, settlement)
    assert directions(entry, vault, settlement) == (Direction.CREDIT, Direction.DEBIT)


def test_liability_to_income_fee_charge() -> None:
    customer = Account("Customer", AccountType.LIABILITY, "GBP")
    fees = Account("Fee Income", AccountType.INCOME, "GBP")
    entry = build_transfer_journal(command(customer, fees, "5.00"), customer, fees)
    assert directions(entry, customer, fees) == (Direction.DEBIT, Direction.CREDIT)


def test_mixed_normal_balances_rejected() -> None:
    settlement = Account("Settlement", AccountType.ASSET, "GBP")
    customer = Account("Customer", AccountType.LIABILITY, "GBP")
    with pytest.raises(InvalidTransferError) as exc:
        build_transfer_journal(command(settlement, customer), settlement, customer)
    assert exc.value.code == "INVALID_TRANSFER"


def test_same_account_rejected() -> None:
    a = Account("A", AccountType.LIABILITY, "GBP")
    with pytest.raises(InvalidTransferError):
        build_transfer_journal(command(a, a), a, a)


def test_currency_mismatch_rejected() -> None:
    a = Account("A", AccountType.LIABILITY, "GBP")
    b = Account("B", AccountType.LIABILITY, "USD")
    with pytest.raises(CurrencyMismatchError):
        build_transfer_journal(command(a, b), a, b)
    with pytest.raises(CurrencyMismatchError):
        build_transfer_journal(command(a, b, currency="USD"), a, b)
