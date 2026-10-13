from __future__ import annotations

import pytest

from corebank.domain.accounts import (
    Account,
    AccountBalance,
    AccountStatus,
    AccountType,
    NormalBalance,
    _luhn_check_digit,
    compute_balance,
    default_allow_negative_balance,
    generate_account_number,
    normal_balance_for,
)
from corebank.domain.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    AccountNotEmptyError,
    InvalidStatusTransitionError,
)
from corebank.domain.money import Money


@pytest.mark.parametrize(
    ("account_type", "expected"),
    [
        (AccountType.ASSET, NormalBalance.DEBIT),
        (AccountType.EXPENSE, NormalBalance.DEBIT),
        (AccountType.LIABILITY, NormalBalance.CREDIT),
        (AccountType.EQUITY, NormalBalance.CREDIT),
        (AccountType.INCOME, NormalBalance.CREDIT),
    ],
)
def test_normal_balance_for(account_type: AccountType, expected: NormalBalance) -> None:
    assert normal_balance_for(account_type) is expected
    assert Account("x", account_type, "GBP").normal_balance is expected


def test_debit_normal_balance_math() -> None:
    debits = Money.of("150.00", "GBP")
    credits = Money.of("100.00", "GBP")
    assert compute_balance(NormalBalance.DEBIT, debits, credits) == Money.of("50.00", "GBP")
    assert compute_balance(NormalBalance.CREDIT, debits, credits) == Money.of("-50.00", "GBP")


def test_credit_normal_balance_math() -> None:
    debits = Money.of("20.00", "GBP")
    credits = Money.of("120.00", "GBP")
    assert compute_balance(NormalBalance.CREDIT, debits, credits) == Money.of("100.00", "GBP")
    assert compute_balance(NormalBalance.DEBIT, debits, credits) == Money.of("-100.00", "GBP")


def test_default_negative_balance_policy() -> None:
    assert default_allow_negative_balance(AccountType.LIABILITY) is False
    for t in (AccountType.ASSET, AccountType.INCOME, AccountType.EXPENSE, AccountType.EQUITY):
        assert default_allow_negative_balance(t) is True
    assert Account("c", AccountType.LIABILITY, "GBP").allow_negative_balance is False
    assert Account(
        "c", AccountType.LIABILITY, "GBP", allow_negative_balance=True
    ).allow_negative_balance


def test_account_number_is_synthetic_with_luhn_check() -> None:
    numbers = {generate_account_number() for _ in range(50)}
    assert len(numbers) == 50
    for number in numbers:
        prefix, body, check = number.split("-")
        assert prefix == "SYN"
        assert len(body) == 10 and body.isdigit()
        assert check == _luhn_check_digit(body)


def test_blank_name_rejected() -> None:
    with pytest.raises(ValueError, match="blank"):
        Account("   ", AccountType.ASSET, "GBP")


def test_ensure_can_post() -> None:
    account = Account("a", AccountType.ASSET, "GBP")
    account.ensure_can_post()
    account.status = AccountStatus.FROZEN
    with pytest.raises(AccountFrozenError):
        account.ensure_can_post()
    account.status = AccountStatus.CLOSED
    with pytest.raises(AccountClosedError):
        account.ensure_can_post()


def test_status_transitions() -> None:
    account = Account("a", AccountType.LIABILITY, "GBP")
    zero = Money.zero("GBP")
    frozen = account.transition_to(AccountStatus.FROZEN, current_balance=zero)
    assert frozen.status is AccountStatus.FROZEN and frozen.version == 2
    assert account.status is AccountStatus.ACTIVE  # original untouched
    active = frozen.transition_to(AccountStatus.ACTIVE, current_balance=zero)
    assert active.status is AccountStatus.ACTIVE
    with pytest.raises(AccountNotEmptyError):
        active.transition_to(AccountStatus.CLOSED, current_balance=Money.of("1", "GBP"))
    closed = active.transition_to(AccountStatus.CLOSED, current_balance=zero)
    with pytest.raises(InvalidStatusTransitionError):
        closed.transition_to(AccountStatus.ACTIVE, current_balance=zero)
    with pytest.raises(InvalidStatusTransitionError):
        account.transition_to(AccountStatus.ACTIVE, current_balance=zero)


def test_account_balance_derive() -> None:
    account = Account("Customer", AccountType.LIABILITY, "GBP")
    bal = AccountBalance.derive(
        account, Money.of("30", "GBP"), Money.of("100", "GBP"), posting_count=3
    )
    assert bal.balance == Money.of("70", "GBP")
    assert bal.normal_balance is NormalBalance.CREDIT
    assert bal.posting_count == 3
