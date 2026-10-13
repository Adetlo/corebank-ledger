from __future__ import annotations

from fastapi import APIRouter, Response, status

from corebank.api.dependencies import ContextDep, IdempotencyKeyDep, TransferServiceDep
from corebank.api.presenters import transfer_response
from corebank.integrations.payment_messages import MODEL_LABEL, PaymentInstruction
from corebank.schemas.common import ErrorResponse
from corebank.schemas.transfers import TransferResponse

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "/instructions",
    status_code=status.HTTP_201_CREATED,
    response_model=TransferResponse,
    summary=f"Execute a payment instruction ({MODEL_LABEL})",
    responses={
        200: {"model": TransferResponse, "description": "Idempotent replay"},
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def execute_payment_instruction(
    body: PaymentInstruction,
    response: Response,
    service: TransferServiceDep,
    ctx: ContextDep,
    idempotency_key: IdempotencyKeyDep,
) -> TransferResponse:
    """Adapt a simplified, ISO 20022-*inspired* instruction into an internal transfer.

    This endpoint does **not** implement ISO 20022 and makes no compliance claim.
    """
    result = service.transfer(body.to_transfer_command(), ctx, idempotency_key=idempotency_key)
    if result.replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return transfer_response(result.journal)
