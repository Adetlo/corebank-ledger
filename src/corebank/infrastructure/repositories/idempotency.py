from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from corebank.infrastructure.models import IdempotencyRecordModel


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    scope: str
    idempotency_key: str
    request_hash: str
    response_status: int
    response_body: dict[str, Any]
    resource_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class IdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        stmt = select(IdempotencyRecordModel).where(
            IdempotencyRecordModel.scope == scope, IdempotencyRecordModel.idempotency_key == key
        )
        model = self._session.execute(stmt).scalar_one_or_none()
        if model is None:
            return None
        return IdempotencyRecord(
            scope=model.scope,
            idempotency_key=model.idempotency_key,
            request_hash=model.request_hash,
            response_status=model.response_status,
            response_body=dict(model.response_body),
            resource_id=model.resource_id,
            created_at=model.created_at,
        )

    def add(self, record: IdempotencyRecord) -> None:
        self._session.add(
            IdempotencyRecordModel(
                scope=record.scope,
                idempotency_key=record.idempotency_key,
                request_hash=record.request_hash,
                response_status=record.response_status,
                response_body=record.response_body,
                resource_id=record.resource_id,
                created_at=record.created_at,
            )
        )
        self._session.flush()
