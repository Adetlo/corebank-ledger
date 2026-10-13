"""Reversals: corrections without ever editing or deleting history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from corebank.application.context import RequestContext
from corebank.application.idempotency import IdempotencyGuard, Replay
from corebank.application.posting_service import post_entry
from corebank.domain.events import JournalReversed
from corebank.domain.exceptions import JournalNotFoundError, MissingIdempotencyKeyError
from corebank.domain.ledger import JournalEntry
from corebank.infrastructure.repositories.audit import AuditEvent, AuditEventType

if TYPE_CHECKING:
    from corebank.application.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ReverseJournalCommand:
    journal_id: UUID
    reason: str | None = None
    reference: str | None = None
    booking_date: date | None = None

    def fingerprint(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "reason": self.reason,
            "reference": self.reference,
            "booking_date": self.booking_date.isoformat() if self.booking_date else None,
        }


@dataclass(frozen=True, slots=True)
class ReversalResult:
    reversal: JournalEntry
    original: JournalEntry
    replayed: bool = False


class ReversalService:
    def __init__(self, uow: UnitOfWork, *, require_idempotency_key: bool = True) -> None:
        self._uow = uow
        self._require_key = require_idempotency_key

    def reverse(
        self, command: ReverseJournalCommand, ctx: RequestContext, *, idempotency_key: str | None
    ) -> ReversalResult:
        if self._require_key and not idempotency_key:
            raise MissingIdempotencyKeyError()
        guard = IdempotencyGuard("journal_entries.reverse", idempotency_key, command.fingerprint())
        try:
            return self._execute(command, ctx, guard)
        except IntegrityError as exc:
            if "uq_idempotency_scope_key" not in str(exc.orig):
                raise
            with self._uow as uow:
                replay = guard.lookup(uow.idempotency)
                if replay is None:
                    raise
                return self._load_replay(uow, replay, ctx)

    def _execute(
        self, command: ReverseJournalCommand, ctx: RequestContext, guard: IdempotencyGuard
    ) -> ReversalResult:
        with self._uow as uow:
            replay = guard.lookup(uow.idempotency)
            if replay is not None:
                return self._load_replay(uow, replay, ctx)
            original = uow.journals.get(command.journal_id, for_update=True)
            if original is None:
                raise JournalNotFoundError(journal_entry_id=str(command.journal_id))
            reversal = original.build_reversal(
                reference=command.reference,
                booking_date=command.booking_date,
                reason=command.reason,
                idempotency_key=guard.key,
            )
            post_entry(uow, reversal, ctx)
            original.mark_reversed(reversal.id)
            uow.journals.mark_reversed(original, reversal.id)
            uow.audit.add(
                AuditEvent(
                    entity_type="journal_entry",
                    entity_id=original.id,
                    event_type=AuditEventType.JOURNAL_REVERSED,
                    correlation_id=ctx.correlation_id,
                    actor=ctx.actor,
                    metadata={
                        "reversal_journal_entry_id": str(reversal.id),
                        "reason": command.reason,
                    },
                )
            )
            uow.add_event(
                JournalReversed(
                    correlation_id=ctx.correlation_id,
                    original_journal_entry_id=original.id,
                    reversal_journal_entry_id=reversal.id,
                )
            )
            guard.remember(
                uow.idempotency,
                resource_id=reversal.id,
                response_status=201,
                response_body={
                    "resource_type": "journal_entry",
                    "resource_id": str(reversal.id),
                    "reversal_of": str(original.id),
                },
            )
            uow.commit()
        return ReversalResult(reversal=reversal, original=original)

    def _load_replay(self, uow: UnitOfWork, replay: Replay, ctx: RequestContext) -> ReversalResult:
        if replay.resource_id is None:
            raise JournalNotFoundError()
        reversal = uow.journals.get(replay.resource_id)
        if reversal is None or reversal.reversal_of is None:
            raise JournalNotFoundError(journal_entry_id=str(replay.resource_id))
        original = uow.journals.get(reversal.reversal_of)
        if original is None:
            raise JournalNotFoundError(journal_entry_id=str(reversal.reversal_of))
        uow.audit.add(
            AuditEvent(
                entity_type="journal_entry",
                entity_id=reversal.id,
                event_type=AuditEventType.IDEMPOTENT_REPLAY,
                correlation_id=ctx.correlation_id,
                actor=ctx.actor,
                metadata={"reference": reversal.reference},
            )
        )
        uow.commit()
        return ReversalResult(reversal=reversal, original=original, replayed=True)
