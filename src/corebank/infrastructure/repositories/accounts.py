from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from corebank.domain.accounts import Account
from corebank.domain.exceptions import ConcurrencyConflictError
from corebank.domain.ledger import EFFECTIVE_STATUSES
from corebank.infrastructure.models import AccountModel, JournalEntryModel, PostingModel
from corebank.infrastructure.repositories._mapping import account_to_domain, account_to_model


@dataclass(frozen=True, slots=True)
class BalanceTotals:
    debit_total: Decimal
    credit_total: Decimal
    posting_count: int


_EFFECTIVE = tuple(s.value for s in EFFECTIVE_STATUSES)


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, account: Account) -> Account:
        model = account_to_model(account)
        self._session.add(model)
        self._session.flush()
        return account_to_domain(model)

    def get(self, account_id: UUID, *, for_update: bool = False) -> Account | None:
        stmt = select(AccountModel).where(AccountModel.id == account_id)
        if for_update:
            stmt = stmt.with_for_update()
        model = self._session.execute(stmt).scalar_one_or_none()
        return account_to_domain(model) if model else None

    def get_by_number(self, account_number: str) -> Account | None:
        stmt = select(AccountModel).where(AccountModel.account_number == account_number)
        model = self._session.execute(stmt).scalar_one_or_none()
        return account_to_domain(model) if model else None

    def get_many_for_update(self, account_ids: Iterable[UUID]) -> dict[UUID, Account]:
        """Lock the given account rows in a deterministic (sorted) order.

        Always locking in ascending id order means two concurrent journal
        entries touching the same accounts cannot deadlock: they queue.
        """
        ordered = sorted(set(account_ids))
        if not ordered:
            return {}
        stmt = (
            select(AccountModel)
            .where(AccountModel.id.in_(ordered))
            .order_by(AccountModel.id)
            .with_for_update()
        )
        models = self._session.execute(stmt).scalars().all()
        return {m.id: account_to_domain(m) for m in models}

    def save(self, account: Account, *, expected_version: int) -> Account:
        """Optimistic update: fails if the row changed since it was read."""
        stmt = (
            update(AccountModel)
            .where(AccountModel.id == account.id, AccountModel.version == expected_version)
            .values(
                account_name=account.account_name,
                status=account.status.value,
                allow_negative_balance=bool(account.allow_negative_balance),
                version=account.version,
                updated_at=account.updated_at,
            )
        )
        result = self._session.execute(stmt)
        if getattr(result, "rowcount", 0) != 1:
            raise ConcurrencyConflictError(account_id=str(account.id))
        return account

    def list(
        self,
        *,
        limit: int,
        offset: int,
        account_type: str | None = None,
        currency: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Account], int]:
        stmt = select(AccountModel)
        if account_type:
            stmt = stmt.where(AccountModel.account_type == account_type)
        if currency:
            stmt = stmt.where(AccountModel.currency == currency)
        if status:
            stmt = stmt.where(AccountModel.status == status)
        total = self._session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        rows = (
            self._session.execute(
                stmt.order_by(AccountModel.created_at, AccountModel.id).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
        return [account_to_domain(m) for m in rows], int(total)

    def balance_totals(self, account_id: UUID, *, as_of_date: date | None = None) -> BalanceTotals:
        """Aggregate effective postings for an account (the source of truth)."""
        debit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "DEBIT", PostingModel.amount), else_=0)), 0
        )
        credit_sum = func.coalesce(
            func.sum(case((PostingModel.direction == "CREDIT", PostingModel.amount), else_=0)), 0
        )
        stmt = (
            select(debit_sum, credit_sum, func.count(PostingModel.id))
            .join(JournalEntryModel, JournalEntryModel.id == PostingModel.journal_entry_id)
            .where(PostingModel.account_id == account_id)
            .where(JournalEntryModel.status.in_(_EFFECTIVE))
        )
        if as_of_date is not None:
            stmt = stmt.where(JournalEntryModel.booking_date <= as_of_date)
        debit, credit, count = self._session.execute(stmt).one()
        return BalanceTotals(Decimal(debit), Decimal(credit), int(count))
