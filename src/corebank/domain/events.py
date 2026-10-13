"""In-process domain events.

Events are plain frozen dataclasses dispatched *after* the owning database
transaction commits, so subscribers never observe uncommitted state. In v1
the only subscriber is a structured-logging handler. A production system would
write these to an outbox table inside the same transaction and relay them to
a broker; see ``docs/OUTBOX.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

logger = logging.getLogger("corebank.events")


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    correlation_id: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def name(self) -> str:
        return type(self).__name__

    def payload(self) -> dict[str, Any]:
        def _coerce(value: Any) -> Any:
            if isinstance(value, UUID | Decimal | datetime):
                return str(value)
            return value

        return {k: _coerce(v) for k, v in asdict(self).items()}


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountCreated(DomainEvent):
    account_id: UUID
    account_type: str
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JournalPosted(DomainEvent):
    journal_entry_id: UUID
    reference: str
    currency: str
    total_debits: Decimal
    posting_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TransferCompleted(DomainEvent):
    journal_entry_id: UUID
    source_account_id: UUID
    destination_account_id: UUID
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JournalReversed(DomainEvent):
    original_journal_entry_id: UUID
    reversal_journal_entry_id: UUID


Handler = Callable[[DomainEvent], None]


class EventDispatcher:
    """Minimal synchronous publish/subscribe used inside one process."""

    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    def publish(self, event: DomainEvent) -> None:
        for handler in list(self._handlers):
            try:
                handler(event)
            except Exception:
                logger.exception("event handler failed", extra={"event": event.name})


def log_event(event: DomainEvent) -> None:
    logger.info(event.name, extra={"event": event.name, "payload": event.payload()})


def default_dispatcher() -> EventDispatcher:
    dispatcher = EventDispatcher()
    dispatcher.subscribe(log_event)
    return dispatcher
