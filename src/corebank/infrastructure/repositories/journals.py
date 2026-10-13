from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session, selectinload

from corebank.domain.exceptions import ConcurrencyConflictError
from corebank.domain.ledger import JournalEntry, JournalStatus
from corebank.infrastructure.models import JournalEntryModel, PostingModel
from corebank.infrastructure.repositories._mapping import journal_to_domain, journal_to_model


@dataclass(frozen=True, slots=True)
class JournalSearch:
    reference: str | None = None
    status: str | None = None
    account_id: UUID | None = None
    booking_date_from: date | None = None
    booking_date_to: date | None = None
    currency: str | None = None
    kind: str | None = None


class JournalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: JournalEntry) -> JournalEntry:
        """Persist the journal and its postings together (one flush)."""
        model = journal_to_model(entry)
        self._session.add(model)
        self._session.flush()
        return entry

    def get(self, journal_id: UUID, *, for_update: bool = False) -> JournalEntry | None:
        stmt = (
            select(JournalEntryModel)
            .options(selectinload(JournalEntryModel.postings))
            .where(JournalEntryModel.id == journal_id)
        )
        if for_update:
            # Lock only the journal row; postings are immutable anyway.
            stmt = stmt.with_for_update(of=JournalEntryModel)
        model = self._session.execute(stmt).scalar_one_or_none()
        return journal_to_domain(model) if model else None

    def mark_reversed(self, original: JournalEntry, reversal_id: UUID) -> None:
        """Link the reversal; guarded so it can only ever happen once."""
        stmt = (
            update(JournalEntryModel)
            .where(
                JournalEntryModel.id == original.id,
                JournalEntryModel.status == JournalStatus.POSTED.value,
                JournalEntryModel.reversed_by.is_(None),
            )
            .values(status=JournalStatus.REVERSED.value, reversed_by=reversal_id)
        )
        result = self._session.execute(stmt)
        if getattr(result, "rowcount", 0) != 1:
            raise ConcurrencyConflictError(
                "Journal entry was reversed concurrently.", journal_entry_id=str(original.id)
            )

    def search(
        self, criteria: JournalSearch, *, limit: int, offset: int
    ) -> tuple[list[JournalEntry], int]:
        stmt = select(JournalEntryModel)
        if criteria.reference:
            stmt = stmt.where(JournalEntryModel.reference == criteria.reference)
        if criteria.status:
            stmt = stmt.where(JournalEntryModel.status == criteria.status)
        if criteria.currency:
            stmt = stmt.where(JournalEntryModel.currency == criteria.currency)
        if criteria.booking_date_from:
            stmt = stmt.where(JournalEntryModel.booking_date >= criteria.booking_date_from)
        if criteria.booking_date_to:
            stmt = stmt.where(JournalEntryModel.booking_date <= criteria.booking_date_to)
        if criteria.kind:
            stmt = stmt.where(JournalEntryModel.metadata_["kind"].astext == criteria.kind)
        if criteria.account_id:
            stmt = stmt.where(
                exists().where(
                    PostingModel.journal_entry_id == JournalEntryModel.id,
                    PostingModel.account_id == criteria.account_id,
                )
            )
        total = self._session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        rows = (
            self._session.execute(
                stmt.options(selectinload(JournalEntryModel.postings))
                .order_by(JournalEntryModel.created_at.desc(), JournalEntryModel.id)
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return [journal_to_domain(m) for m in rows], int(total)

    def count_postings(self) -> int:
        return int(self._session.execute(select(func.count(PostingModel.id))).scalar_one())

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)
