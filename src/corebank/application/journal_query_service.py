from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from corebank.domain.exceptions import JournalNotFoundError
from corebank.domain.ledger import JournalEntry
from corebank.infrastructure.repositories import JournalSearch
from corebank.infrastructure.repositories.audit import AuditEvent

if TYPE_CHECKING:
    from corebank.application.unit_of_work import UnitOfWork


class JournalQueryService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def get(self, journal_id: UUID) -> JournalEntry:
        with self._uow as uow:
            journal = uow.journals.get(journal_id)
        if journal is None:
            raise JournalNotFoundError(journal_entry_id=str(journal_id))
        return journal

    def search(
        self, criteria: JournalSearch, *, limit: int, offset: int
    ) -> tuple[list[JournalEntry], int]:
        with self._uow as uow:
            return uow.journals.search(criteria, limit=limit, offset=offset)

    def audit_trail(self, entity_id: UUID, *, limit: int = 100) -> list[AuditEvent]:
        with self._uow as uow:
            return uow.audit.list_for_entity(entity_id, limit=limit)
