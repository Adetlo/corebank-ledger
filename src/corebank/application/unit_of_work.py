"""Unit of Work: one database transaction per use case.

Every mutating use case runs inside ``with uow:`` and ends with an explicit
``uow.commit()``. Leaving the block for any other reason rolls the whole
transaction back, which is what guarantees invariant 3 (atomic posting):
journal row, posting rows, audit rows and the idempotency record either all
land or none do.

Domain events are buffered and dispatched only *after* a successful commit so
subscribers never observe uncommitted state.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from corebank.domain.events import DomainEvent, EventDispatcher, default_dispatcher
from corebank.infrastructure.repositories import (
    AccountRepository,
    AuditRepository,
    IdempotencyRepository,
    JournalRepository,
    ReconciliationRepository,
)


class UnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher or default_dispatcher()
        self._session: Session | None = None
        self._pending_events: list[DomainEvent] = []
        self.committed = False

    # ----- context management --------------------------------------------------
    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self._session.begin()
        self._pending_events = []
        self.committed = False
        self.accounts = AccountRepository(self._session)
        self.journals = JournalRepository(self._session)
        self.idempotency = IdempotencyRepository(self._session)
        self.audit = AuditRepository(self._session)
        self.reconciliation = ReconciliationRepository(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self.committed:
                self.rollback()
        finally:
            if self._session is not None:
                self._session.close()
                self._session = None

    # ----- transaction control ---------------------------------------------------
    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside of its context")
        return self._session

    def commit(self) -> None:
        self.session.commit()
        self.committed = True
        events, self._pending_events = self._pending_events, []
        for event in events:
            self._dispatcher.publish(event)

    def rollback(self) -> None:
        if self._session is not None and self._session.in_transaction():
            self._session.rollback()
        self._pending_events = []

    def flush(self) -> None:
        self.session.flush()

    def add_event(self, event: DomainEvent) -> None:
        self._pending_events.append(event)
