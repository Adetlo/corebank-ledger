"""Reconciliation: prove the ledger balances from the postings themselves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from corebank.domain.accounts import NormalBalance, compute_balance
from corebank.domain.money import Money, validate_currency

if TYPE_CHECKING:
    from corebank.application.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class TrialBalanceLine:
    account_id: UUID
    account_number: str
    account_name: str
    account_type: str
    normal_balance: NormalBalance
    currency: str
    debit_total: Money
    credit_total: Money
    net_balance: Money


@dataclass(frozen=True, slots=True)
class TrialBalance:
    currency: str
    as_of_date: date | None
    lines: list[TrialBalanceLine]
    total_debits: Money
    total_credits: Money

    @property
    def difference(self) -> Money:
        return self.total_debits - self.total_credits

    @property
    def balanced(self) -> bool:
        return self.difference.is_zero


@dataclass(frozen=True, slots=True)
class LedgerCheckLine:
    currency: str
    total_debits: Money
    total_credits: Money
    difference: Money
    balanced: bool
    posting_count: int


@dataclass(frozen=True, slots=True)
class LedgerCheck:
    as_of_date: date | None
    currencies: list[LedgerCheckLine]
    unbalanced_journal_ids: list[UUID]

    @property
    def balanced(self) -> bool:
        return all(c.balanced for c in self.currencies) and not self.unbalanced_journal_ids


class ReconciliationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def trial_balance(self, *, currency: str, as_of_date: date | None = None) -> TrialBalance:
        code = validate_currency(currency)
        with self._uow as uow:
            rows = uow.reconciliation.account_totals(currency=code, as_of_date=as_of_date)
        lines: list[TrialBalanceLine] = []
        total_debits = Money.zero(code)
        total_credits = Money.zero(code)
        for row in rows:
            debit = Money(row.debit_total, code)
            credit = Money(row.credit_total, code)
            normal = NormalBalance(row.normal_balance)
            lines.append(
                TrialBalanceLine(
                    account_id=row.account_id,
                    account_number=row.account_number,
                    account_name=row.account_name,
                    account_type=row.account_type,
                    normal_balance=normal,
                    currency=code,
                    debit_total=debit,
                    credit_total=credit,
                    net_balance=compute_balance(normal, debit, credit),
                )
            )
            total_debits = total_debits + debit
            total_credits = total_credits + credit
        return TrialBalance(
            currency=code,
            as_of_date=as_of_date,
            lines=lines,
            total_debits=total_debits,
            total_credits=total_credits,
        )

    def ledger_check(self, *, as_of_date: date | None = None) -> LedgerCheck:
        with self._uow as uow:
            rows = uow.reconciliation.currency_totals(as_of_date=as_of_date)
            unbalanced = uow.reconciliation.unbalanced_journals()
        lines = []
        for row in rows:
            debit = Money(row.debit_total, row.currency)
            credit = Money(row.credit_total, row.currency)
            diff = debit - credit
            lines.append(
                LedgerCheckLine(
                    currency=row.currency,
                    total_debits=debit,
                    total_credits=credit,
                    difference=diff,
                    balanced=diff.is_zero,
                    posting_count=row.posting_count,
                )
            )
        return LedgerCheck(
            as_of_date=as_of_date, currencies=lines, unbalanced_journal_ids=unbalanced
        )
