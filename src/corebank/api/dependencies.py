"""FastAPI dependency wiring for settings, database and services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Request

from corebank.application.account_service import AccountService
from corebank.application.context import RequestContext
from corebank.application.journal_query_service import JournalQueryService
from corebank.application.posting_service import PostingService
from corebank.application.reconciliation_service import ReconciliationService
from corebank.application.reversal_service import ReversalService
from corebank.application.transfer_service import TransferService
from corebank.application.unit_of_work import UnitOfWork
from corebank.config import Settings
from corebank.logging import correlation_id_var

UowFactory = Callable[[], UnitOfWork]


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_uow(request: Request) -> UnitOfWork:
    factory: UowFactory = request.app.state.uow_factory
    return factory()


def get_context(
    actor: Annotated[str | None, Header(alias="X-Actor", max_length=128)] = None,
) -> RequestContext:
    """Actor is informational in v1; authentication is out of scope (see SECURITY.md)."""
    return RequestContext(correlation_id=correlation_id_var.get() or "", actor=actor)


def get_idempotency_key(
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=128,
            description="Client-generated unique key making the request safely retryable.",
        ),
    ] = None,
) -> str | None:
    return idempotency_key


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
UowDep = Annotated[UnitOfWork, Depends(get_uow)]
ContextDep = Annotated[RequestContext, Depends(get_context)]
IdempotencyKeyDep = Annotated[str | None, Depends(get_idempotency_key)]


def get_account_service(uow: UowDep) -> AccountService:
    return AccountService(uow)


def get_posting_service(uow: UowDep, settings: SettingsDep) -> PostingService:
    return PostingService(uow, require_idempotency_key=settings.require_idempotency_key)


def get_transfer_service(uow: UowDep, settings: SettingsDep) -> TransferService:
    return TransferService(uow, require_idempotency_key=settings.require_idempotency_key)


def get_reversal_service(uow: UowDep, settings: SettingsDep) -> ReversalService:
    return ReversalService(uow, require_idempotency_key=settings.require_idempotency_key)


def get_journal_query_service(uow: UowDep) -> JournalQueryService:
    return JournalQueryService(uow)


def get_reconciliation_service(uow: UowDep) -> ReconciliationService:
    return ReconciliationService(uow)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
PostingServiceDep = Annotated[PostingService, Depends(get_posting_service)]
TransferServiceDep = Annotated[TransferService, Depends(get_transfer_service)]
ReversalServiceDep = Annotated[ReversalService, Depends(get_reversal_service)]
JournalQueryServiceDep = Annotated[JournalQueryService, Depends(get_journal_query_service)]
ReconciliationServiceDep = Annotated[ReconciliationService, Depends(get_reconciliation_service)]
