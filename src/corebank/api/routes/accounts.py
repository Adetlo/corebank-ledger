from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from corebank.api.dependencies import AccountServiceDep, ContextDep
from corebank.api.presenters import account_response, balance_response
from corebank.api.routes._pagination import LimitQ, OffsetQ
from corebank.application.account_service import CreateAccountCommand
from corebank.domain.accounts import AccountStatus, AccountType
from corebank.schemas.accounts import (
    AccountCreate,
    AccountResponse,
    AccountStatusUpdate,
    BalanceResponse,
)
from corebank.schemas.common import ErrorResponse, Page

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=AccountResponse,
    summary="Create a ledger account",
    responses={422: {"model": ErrorResponse}},
)
def create_account(
    body: AccountCreate, service: AccountServiceDep, ctx: ContextDep
) -> AccountResponse:
    """Create an account with a generated synthetic account number.

    The normal balance (DEBIT/CREDIT) is derived from the account type and
    cannot be chosen by the client.
    """
    account = service.create_account(
        CreateAccountCommand(
            account_name=body.account_name,
            account_type=body.account_type,
            currency=body.currency,
            allow_negative_balance=body.allow_negative_balance,
        ),
        ctx,
    )
    return account_response(account)


@router.get("", response_model=Page[AccountResponse], summary="List accounts")
def list_accounts(
    service: AccountServiceDep,
    limit: LimitQ = 50,
    offset: OffsetQ = 0,
    account_type: Annotated[AccountType | None, Query()] = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    status_filter: Annotated[AccountStatus | None, Query(alias="status")] = None,
) -> Page[AccountResponse]:
    items, total = service.list_accounts(
        limit=limit,
        offset=offset,
        account_type=account_type,
        currency=currency,
        status=status_filter,
    )
    return Page(items=[account_response(a) for a in items], total=total, limit=limit, offset=offset)


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    summary="Get an account",
    responses={404: {"model": ErrorResponse}},
)
def get_account(account_id: UUID, service: AccountServiceDep) -> AccountResponse:
    return account_response(service.get_account(account_id))


@router.get(
    "/{account_id}/balance",
    response_model=BalanceResponse,
    summary="Get an account balance derived from postings",
    responses={404: {"model": ErrorResponse}},
)
def get_balance(
    account_id: UUID,
    service: AccountServiceDep,
    as_of_date: Annotated[
        date | None, Query(description="Include postings with booking_date <= this date")
    ] = None,
) -> BalanceResponse:
    """Balances are computed from effective postings, never read from a stored column."""
    return balance_response(service.get_balance(account_id, as_of_date=as_of_date))


@router.post(
    "/{account_id}/status",
    response_model=AccountResponse,
    summary="Change account status (freeze, reactivate, close)",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def change_status(
    account_id: UUID, body: AccountStatusUpdate, service: AccountServiceDep, ctx: ContextDep
) -> AccountResponse:
    """Closing requires a zero balance; closed accounts cannot be reopened."""
    return account_response(service.change_status(account_id, body.status, ctx))
