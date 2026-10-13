from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from corebank.api.dependencies import ReconciliationServiceDep
from corebank.api.presenters import ledger_check_response, trial_balance_response
from corebank.schemas.common import ErrorResponse
from corebank.schemas.reconciliation import LedgerCheckResponse, TrialBalanceResponse

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get(
    "/trial-balance",
    response_model=TrialBalanceResponse,
    summary="Trial balance per account for one currency",
    responses={422: {"model": ErrorResponse}},
)
def trial_balance(
    service: ReconciliationServiceDep,
    currency: Annotated[str, Query(min_length=3, max_length=3, examples=["GBP"])] = "GBP",
    as_of_date: Annotated[date | None, Query()] = None,
) -> TrialBalanceResponse:
    """For a healthy ledger ``difference`` is ``0`` and ``balanced`` is ``true``."""
    return trial_balance_response(service.trial_balance(currency=currency, as_of_date=as_of_date))


@router.get(
    "/ledger-check",
    response_model=LedgerCheckResponse,
    summary="Ledger-wide debit/credit integrity check across all currencies",
)
def ledger_check(
    service: ReconciliationServiceDep,
    as_of_date: Annotated[date | None, Query()] = None,
) -> LedgerCheckResponse:
    """Recomputes totals straight from the postings and lists any unbalanced journal ids."""
    return ledger_check_response(service.ledger_check(as_of_date=as_of_date))
