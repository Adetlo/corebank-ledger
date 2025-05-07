from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Response, status

from corebank.api.dependencies import ContextDep, IdempotencyKeyDep, TransferServiceDep
from corebank.api.presenters import transfer_response
from corebank.domain.money import Money
from corebank.domain.transactions import TransferCommand
from corebank.schemas.common import ErrorResponse
from corebank.schemas.transfers import TransferCreate, TransferResponse

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TransferResponse,
    summary="Transfer value between two accounts",
    responses={
        200: {"model": TransferResponse, "description": "Idempotent replay"},
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "Insufficient funds, idempotency conflict"},
        422: {"model": ErrorResponse},
    },
)
def create_transfer(
    body: TransferCreate,
    response: Response,
    service: TransferServiceDep,
    ctx: ContextDep,
    idempotency_key: IdempotencyKeyDep,
) -> TransferResponse:
    """Book a transfer as one balanced two-leg journal entry.

    The source balance decreases and the destination balance increases, each in
    its natural sign. Both accounts must share the same normal balance (e.g. two
    customer LIABILITY accounts); see ``docs/LEDGER_INVARIANTS.md``.
    """
    booking_date = body.booking_date or datetime.now(UTC).date()
    result = service.transfer(
        TransferCommand(
            source_account_id=body.source_account_id,
            destination_account_id=body.destination_account_id,
            money=Money(body.amount, body.currency),
            reference=body.reference,
            booking_date=booking_date,
            value_date=body.value_date or booking_date,
            description=body.description,
            metadata=body.metadata or {},
        ),
        ctx,
        idempotency_key=idempotency_key,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return transfer_response(result.journal)


@router.get(
    "/{transfer_id}",
    response_model=TransferResponse,
    summary="Get a transfer",
    responses={404: {"model": ErrorResponse}},
)
def get_transfer(transfer_id: UUID, service: TransferServiceDep) -> TransferResponse:
    return transfer_response(service.get_transfer(transfer_id))
