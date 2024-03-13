from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from corebank.infrastructure.models import AuditEventModel


class AuditEventType(StrEnum):
    ACCOUNT_CREATED = "ACCOUNT_CREATED"
    ACCOUNT_STATUS_CHANGED = "ACCOUNT_STATUS_CHANGED"
    JOURNAL_CREATED = "JOURNAL_CREATED"
    JOURNAL_POSTED = "JOURNAL_POSTED"
    JOURNAL_REVERSED = "JOURNAL_REVERSED"
    TRANSFER_CREATED = "TRANSFER_CREATED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    entity_type: str
    entity_id: UUID
    event_type: AuditEventType
    correlation_id: str
    actor: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditRepository:
    """Append-only: there is intentionally no update or delete method."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(
            AuditEventModel(
                id=event.id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                event_type=event.event_type.value,
                occurred_at=event.occurred_at,
                correlation_id=event.correlation_id,
                actor=event.actor,
                metadata_=dict(event.metadata),
            )
        )

    def list_for_entity(self, entity_id: UUID, *, limit: int = 100) -> list[AuditEvent]:
        stmt = (
            select(AuditEventModel)
            .where(AuditEventModel.entity_id == entity_id)
            .order_by(AuditEventModel.occurred_at, AuditEventModel.id)
            .limit(limit)
        )
        return [self._to_domain(m) for m in self._session.execute(stmt).scalars().all()]

    def list_for_correlation(self, correlation_id: str, *, limit: int = 100) -> list[AuditEvent]:
        stmt = (
            select(AuditEventModel)
            .where(AuditEventModel.correlation_id == correlation_id)
            .order_by(AuditEventModel.occurred_at, AuditEventModel.id)
            .limit(limit)
        )
        return [self._to_domain(m) for m in self._session.execute(stmt).scalars().all()]

    @staticmethod
    def _to_domain(model: AuditEventModel) -> AuditEvent:
        return AuditEvent(
            id=model.id,
            entity_type=model.entity_type,
            entity_id=model.entity_id,
            event_type=AuditEventType(model.event_type),
            correlation_id=model.correlation_id,
            actor=model.actor,
            metadata=dict(model.metadata_ or {}),
            occurred_at=model.occurred_at,
        )
