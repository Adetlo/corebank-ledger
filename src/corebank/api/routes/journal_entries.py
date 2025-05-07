from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from corebank.api.dependencies import (
    ContextDep,
    IdempotencyKeyDep,
    JournalQueryServiceDep,
    PostingServiceDep,
    ReversalServiceDep,
)
from corebank.api.presenters import audit_event_response, journal_response
from corebank.api.routes._pagination import LimitQ, OffsetQ
from corebank.application.posting_service import PostingLine, PostJournalCommand
from corebank.application.reversal_service import ReverseJournalCommand
from corebank.domain.ledger import JournalStatus
from corebank.infrastructure.repositories import JournalSearch
from corebank.schemas.common import ErrorResponse, Page
from corebank.schemas.journal import (
    AuditEventResponse,
    JournalEntryCreate,
    JournalEntryResponse,
    ReversalCreate,
)

router = APIRouter(prefix="/journal-entries", tags=["journal-entries"])

_MUTATION_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": JournalEntryResponse, "description": "Idempotent replay of an earlier request"},
    400: {"model": ErrorResponse, "description": "Missing Idempotency-Key"},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse, "description": "Conflict (idempotency, funds, account state)"},
    422: {"model": ErrorResponse, "description": "Validation or unbalanced journal"},
}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=JournalEntryResponse,
    summary="Post a balanced journal entry",
    responses=_MUTATION_RESPONSES,
)
def post_journal_entry(
    body: JournalEntryCreate,
    response: Response,
    service: PostingServiceDep,
    ctx: ContextDep,
    idempotency_key: IdempotencyKeyDep,
) -> JournalEntryResponse:
    """Create and post a journal entry atomically.

    * Debits must equal credits (``UNBALANCED_JOURNAL`` otherwise).
    * All postings must share one currency matching every account.
    * Requires an ``Idempotency-Key`` header; replays return ``200`` with the
      original entry and the ``Idempotent-Replayed: true`` header.
    """
    result = service.post_journal(
        PostJournalCommand(
            reference=body.reference,
            description=body.description,
            booking_date=body.booking_date,
            value_date=body.value_date,
            metadata=body.metadata or {},
            postings=[
                PostingLine(
                    account_id=p.account_id,
                    direction=p.direction,
                    amount=p.amount,
                    currency=p.currency,
                )
                for p in body.postings
            ],
        ),
        ctx,
        idempotency_key=idempotency_key,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return journal_response(result.journal)


@router.get("", response_model=Page[JournalEntryResponse], summary="Search journal entries")
def search_journal_entries(
    service: JournalQueryServiceDep,
    limit: LimitQ = 50,
    offset: OffsetQ = 0,
    reference: Annotated[str | None, Query(max_length=64)] = None,
    status_filter: Annotated[JournalStatus | None, Query(alias="status")] = None,
    account_id: Annotated[UUID | None, Query()] = None,
    booking_date_from: Annotated[date | None, Query()] = None,
    booking_date_to: Annotated[date | None, Query()] = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
) -> Page[JournalEntryResponse]:
    items, total = service.search(
        JournalSearch(
            reference=reference,
            status=status_filter.value if status_filter else None,
            account_id=account_id,
            booking_date_from=booking_date_from,
            booking_date_to=booking_date_to,
            currency=currency.upper() if currency else None,
        ),
        limit=limit,
        offset=offset,
    )
    return Page(items=[journal_response(j) for j in items], total=total, limit=limit, offset=offset)


@router.get(
    "/{journal_id}",
    response_model=JournalEntryResponse,
    summary="Get a journal entry",
    responses={404: {"model": ErrorResponse}},
)
def get_journal_entry(journal_id: UUID, service: JournalQueryServiceDep) -> JournalEntryResponse:
    return journal_response(service.get(journal_id))


@router.get(
    "/{journal_id}/audit-events",
    response_model=list[AuditEventResponse],
    summary="Audit trail for a journal entry",
)
def journal_audit_events(
    journal_id: UUID, service: JournalQueryServiceDep
) -> list[AuditEventResponse]:
    return [audit_event_response(e) for e in service.audit_trail(journal_id)]


@router.post(
    "/{journal_id}/reverse",
    status_code=status.HTTP_201_CREATED,
    response_model=JournalEntryResponse,
    summary="Reverse a posted journal entry",
    responses=_MUTATION_RESPONSES,
)
def reverse_journal_entry(
    journal_id: UUID,
    response: Response,
    service: ReversalServiceDep,
    ctx: ContextDep,
    idempotency_key: IdempotencyKeyDep,
    body: ReversalCreate | None = None,
) -> JournalEntryResponse:
    """Create a new entry with opposite postings and link both ways.

    The original is never modified beyond ``status=REVERSED`` and
    ``reversed_by``; a second reversal attempt returns ``JOURNAL_ALREADY_REVERSED``.
    """
    body = body or ReversalCreate()
    result = service.reverse(
        ReverseJournalCommand(
            journal_id=journal_id,
            reason=body.reason,
            reference=body.reference,
            booking_date=body.booking_date,
        ),
        ctx,
        idempotency_key=idempotency_key,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return journal_response(result.reversal)
