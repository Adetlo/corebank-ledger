from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from corebank.domain.ledger import EFFECTIVE_STATUSES
from corebank.infrastructure.models import AccountModel, JournalEntryModel, PostingModel

_EFFECTIVE = tuple(s.value for s in EFFECTIVE_STATUSES)


@dataclass(frozen=True, slots=True)
class AccountTotalsRow:
    account_id: UUID
    account_number: str
    account_name: str
    account_type: str
    normal_balance: str
    currency: str
    debit_total: Decimal
    credit_total: Decimal


@dataclass(frozen=True, slots=True)
class CurrencyTotalsRow:
    currency: str
    debit_total: Decimal
    credit_total: Decimal
    posting_count: int


class ReconciliationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def account_totals(
        self, *, currency: str | None = None, as_of_date: date | None = None
    ) -> list[AccountTotalsRow]:
        debit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "DEBIT", PostingModel.amount), else_=0)), 0
        )
        credit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "CREDIT", PostingModel.amount), else_=0)), 0
        )
        posting_filter: list[ColumnElement[bool]] = [JournalEntryModel.status.in_(_EFFECTIVE)]
        if as_of_date is not None:
            posting_filter.append(JournalEntryModel.booking_date <= as_of_date)
        effective = (
            select(
                PostingModel.account_id.label("account_id"),
                debit_sum.label("debit_total"),
                credit_sum.label("credit_total"),
            )
            .join(JournalEntryModel, JournalEntryModel.id == PostingModel.journal_entry_id)
            .where(*posting_filter)
            .group_by(PostingModel.account_id)
            .subquery()
        )
        stmt = (
            select(
                AccountModel.id,
                AccountModel.account_number,
                AccountModel.account_name,
                AccountModel.account_type,
                AccountModel.normal_balance,
                AccountModel.currency,
                func.coalesce(effective.c.debit_total, 0),
                func.coalesce(effective.c.credit_total, 0),
            )
            .outerjoin(effective, effective.c.account_id == AccountModel.id)
            .order_by(AccountModel.account_type, AccountModel.account_number)
        )
        if currency:
            stmt = stmt.where(AccountModel.currency == currency)
        return [
            AccountTotalsRow(
                account_id=row[0],
                account_number=row[1],
                account_name=row[2],
                account_type=row[3],
                normal_balance=row[4],
                currency=row[5],
                debit_total=Decimal(row[6]),
                credit_total=Decimal(row[7]),
            )
            for row in self._session.execute(stmt).all()
        ]

    def currency_totals(self, *, as_of_date: date | None = None) -> list[CurrencyTotalsRow]:
        debit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "DEBIT", PostingModel.amount), else_=0)), 0
        )
        credit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "CREDIT", PostingModel.amount), else_=0)), 0
        )
        stmt = (
            select(PostingModel.currency, debit_sum, credit_sum, func.count(PostingModel.id))
            .join(JournalEntryModel, JournalEntryModel.id == PostingModel.journal_entry_id)
            .where(JournalEntryModel.status.in_(_EFFECTIVE))
            .group_by(PostingModel.currency)
            .order_by(PostingModel.currency)
        )
        if as_of_date is not None:
            stmt = stmt.where(JournalEntryModel.booking_date <= as_of_date)
        return [
            CurrencyTotalsRow(
                currency=row[0],
                debit_total=Decimal(row[1]),
                credit_total=Decimal(row[2]),
                posting_count=int(row[3]),
            )
            for row in self._session.execute(stmt).all()
        ]

    def unbalanced_journals(self) -> list[UUID]:
        """Journals whose effective postings do not balance (should always be empty)."""
        debit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "DEBIT", PostingModel.amount), else_=0)), 0
        )
        credit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "CREDIT", PostingModel.amount), else_=0)), 0
        )
        stmt = (
            select(PostingModel.journal_entry_id)
            .join(JournalEntryModel, JournalEntryModel.id == PostingModel.journal_entry_id)
            .where(JournalEntryModel.status.in_(_EFFECTIVE))
            .group_by(PostingModel.journal_entry_id)
            .having(debit_sum != credit_sum)
        )
        return [row[0] for row in self._session.execute(stmt).all()]
