from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from corebank.application.context import RequestContext
from corebank.application.idempotency import IdempotencyGuard, Replay
from corebank.application.posting_service import lock_accounts, post_entry
from corebank.domain.events import TransferCompleted
from corebank.domain.exceptions import JournalNotFoundError, MissingIdempotencyKeyError
from corebank.domain.ledger import JournalEntry
from corebank.domain.transactions import TransferCommand, build_transfer_journal
from corebank.infrastructure.repositories.audit import AuditEvent, AuditEventType

if TYPE_CHECKING:
    from corebank.application.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class TransferResult:
    journal: JournalEntry
    replayed: bool = False


def transfer_fingerprint(command: TransferCommand) -> dict[str, Any]:
    return {
        "source_account_id": str(command.source_account_id),
        "destination_account_id": str(command.destination_account_id),
        "amount": command.money.as_string(),
        "currency": command.money.currency,
        "reference": command.reference,
        "booking_date": command.booking_date.isoformat(),
        "value_date": (command.value_date or command.booking_date).isoformat(),
        "description": command.description,
        "metadata": command.metadata,
    }


class TransferService:
    """Use case: move value between two accounts as one balanced journal entry."""

    def __init__(self, uow: UnitOfWork, *, require_idempotency_key: bool = True) -> None:
        self._uow = uow
        self._require_key = require_idempotency_key

    def transfer(
        self, command: TransferCommand, ctx: RequestContext, *, idempotency_key: str | None
    ) -> TransferResult:
        if self._require_key and not idempotency_key:
            raise MissingIdempotencyKeyError()
        guard = IdempotencyGuard("transfers.create", idempotency_key, transfer_fingerprint(command))
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
        self, command: TransferCommand, ctx: RequestContext, guard: IdempotencyGuard
    ) -> TransferResult:
        with self._uow as uow:
            replay = guard.lookup(uow.idempotency)
            if replay is not None:
                return self._load_replay(uow, replay, ctx)
            accounts = lock_accounts(
                uow, {command.source_account_id, command.destination_account_id}
            )
            entry = build_transfer_journal(
                command,
                accounts[command.source_account_id],
                accounts[command.destination_account_id],
                idempotency_key=guard.key,
            )
            post_entry(uow, entry, ctx)
            uow.audit.add(
                AuditEvent(
                    entity_type="transfer",
                    entity_id=entry.id,
                    event_type=AuditEventType.TRANSFER_CREATED,
                    correlation_id=ctx.correlation_id,
                    actor=ctx.actor,
                    metadata={
                        "reference": entry.reference,
                        "source_account_id": str(command.source_account_id),
                        "destination_account_id": str(command.destination_account_id),
                        "amount": command.money.as_string(),
                        "currency": command.money.currency,
                    },
                )
            )
            uow.add_event(
                TransferCompleted(
                    correlation_id=ctx.correlation_id,
                    journal_entry_id=entry.id,
                    source_account_id=command.source_account_id,
                    destination_account_id=command.destination_account_id,
                    amount=command.money.amount,
                    currency=command.money.currency,
                )
            )
            guard.remember(
                uow.idempotency,
                resource_id=entry.id,
                response_status=201,
                response_body={"resource_type": "transfer", "resource_id": str(entry.id)},
            )
            uow.commit()
        return TransferResult(journal=entry)

    def _load_replay(self, uow: UnitOfWork, replay: Replay, ctx: RequestContext) -> TransferResult:
        if replay.resource_id is None:
            raise JournalNotFoundError()
        journal = uow.journals.get(replay.resource_id)
        if journal is None:
            raise JournalNotFoundError(journal_entry_id=str(replay.resource_id))
        uow.audit.add(
            AuditEvent(
                entity_type="transfer",
                entity_id=journal.id,
                event_type=AuditEventType.IDEMPOTENT_REPLAY,
                correlation_id=ctx.correlation_id,
                actor=ctx.actor,
                metadata={"reference": journal.reference},
            )
        )
        uow.commit()
        return TransferResult(journal=journal, replayed=True)

    def get_transfer(self, transfer_id: Any) -> JournalEntry:
        with self._uow as uow:
            journal = uow.journals.get(transfer_id)
        if journal is None or journal.metadata.get("kind") != "TRANSFER":
            raise JournalNotFoundError("Transfer not found.", transfer_id=str(transfer_id))
        return journal
