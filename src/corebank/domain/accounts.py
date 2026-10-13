"""Ledger account aggregate and the debit/credit sign rules.

Accounting sign logic
---------------------
Every account has a *normal balance* derived from its type:

===========  ==============  ======================  ======================
Type         Normal balance  Debit posting           Credit posting
===========  ==============  ======================  ======================
ASSET        DEBIT           increases balance       decreases balance
EXPENSE      DEBIT           increases balance       decreases balance
LIABILITY    CREDIT          decreases balance       increases balance
EQUITY       CREDIT          decreases balance       increases balance
INCOME       CREDIT          decreases balance       increases balance
===========  ==============  ======================  ======================

Therefore::

    balance(DEBIT-normal account)  = total_debits  - total_credits
    balance(CREDIT-normal account) = total_credits - total_debits

A positive balance always means "the account holds its normal kind of value"
(an asset holds value, a liability is owed). A customer deposit account is a
LIABILITY of the bank: crediting it increases what the bank owes the customer.

Balances are **derived** from postings, never stored as mutable truth; see
``docs/LEDGER_INVARIANTS.md`` invariant 6.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from corebank.domain.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    AccountNotEmptyError,
    InvalidStatusTransitionError,
)
from corebank.domain.money import Money, validate_currency


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class NormalBalance(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


_NORMAL_BALANCE: dict[AccountType, NormalBalance] = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.INCOME: NormalBalance.CREDIT,
}


def normal_balance_for(account_type: AccountType) -> NormalBalance:
    """Return the normal balance side for an account type."""
    return _NORMAL_BALANCE[AccountType(account_type)]


def default_allow_negative_balance(account_type: AccountType) -> bool:
    """Simplified policy: customer-style LIABILITY accounts may not be overdrawn.

    Ledger/GL accounts (assets, income, expense, equity) are allowed to swing
    negative because that is routine for control accounts (a suspense account
    can legitimately be on either side). The flag is explicit per account and
    can be overridden at creation time; see ``docs/LEDGER_INVARIANTS.md``.
    """
    return AccountType(account_type) != AccountType.LIABILITY


def compute_balance(normal_balance: NormalBalance, debits: Money, credits: Money) -> Money:
    """Net balance in the account's natural sign (see module docstring)."""
    if NormalBalance(normal_balance) is NormalBalance.DEBIT:
        return debits - credits
    return credits - debits


_ALLOWED_TRANSITIONS: dict[AccountStatus, set[AccountStatus]] = {
    AccountStatus.ACTIVE: {AccountStatus.FROZEN, AccountStatus.CLOSED},
    AccountStatus.FROZEN: {AccountStatus.ACTIVE, AccountStatus.CLOSED},
    AccountStatus.CLOSED: set(),
}


def _luhn_check_digit(digits: str) -> str:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 0:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return str((10 - total % 10) % 10)


def generate_account_number() -> str:
    """Generate an obviously synthetic account number: ``SYN-<10 digits>-<check>``.

    The ``SYN`` prefix marks the number as synthetic. The body is random (not
    sequential, so it leaks no information about account volume) and a Luhn
    check digit allows cheap typo detection, mirroring real schemes without
    copying any institution's format.
    """
    body = "".join(str(secrets.randbelow(10)) for _ in range(10))
    return f"SYN-{body}-{_luhn_check_digit(body)}"


@dataclass(slots=True)
class Account:
    """A ledger account. Balances live in postings, not here."""

    account_name: str
    account_type: AccountType
    currency: str
    id: UUID = field(default_factory=uuid4)
    account_number: str = field(default_factory=generate_account_number)
    status: AccountStatus = AccountStatus.ACTIVE
    normal_balance: NormalBalance = field(init=False)
    allow_negative_balance: bool | None = None
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.account_type = AccountType(self.account_type)
        self.status = AccountStatus(self.status)
        self.currency = validate_currency(self.currency)
        self.normal_balance = normal_balance_for(self.account_type)
        if self.allow_negative_balance is None:
            self.allow_negative_balance = default_allow_negative_balance(self.account_type)
        name = self.account_name.strip()
        if not name:
            raise ValueError("account_name must not be blank")
        self.account_name = name

    @property
    def is_active(self) -> bool:
        return self.status is AccountStatus.ACTIVE

    def ensure_can_post(self) -> None:
        """Raise if postings to this account are not allowed."""
        if self.status is AccountStatus.CLOSED:
            raise AccountClosedError(account_id=str(self.id))
        if self.status is AccountStatus.FROZEN:
            raise AccountFrozenError(account_id=str(self.id))

    def transition_to(self, new_status: AccountStatus, *, current_balance: Money) -> Account:
        """Return a copy with ``new_status`` applied, enforcing lifecycle rules."""
        target = AccountStatus(new_status)
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidStatusTransitionError(
                f"Cannot move account from {self.status} to {target}.",
                account_id=str(self.id),
                from_status=self.status,
                to_status=target,
            )
        if target is AccountStatus.CLOSED and not current_balance.is_zero:
            raise AccountNotEmptyError(account_id=str(self.id), balance=current_balance.as_string())
        return replace(self, status=target, version=self.version + 1, updated_at=datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """A balance *derived* from postings as of a point in time."""

    account_id: UUID
    currency: str
    debit_total: Money
    credit_total: Money
    balance: Money
    normal_balance: NormalBalance
    as_of_date: date | None = None
    posting_count: int = 0

    @classmethod
    def derive(
        cls,
        account: Account,
        debit_total: Money,
        credit_total: Money,
        *,
        as_of_date: date | None = None,
        posting_count: int = 0,
    ) -> AccountBalance:
        return cls(
            account_id=account.id,
            currency=account.currency,
            debit_total=debit_total,
            credit_total=credit_total,
            balance=compute_balance(account.normal_balance, debit_total, credit_total),
            normal_balance=account.normal_balance,
            as_of_date=as_of_date,
            posting_count=posting_count,
        )
