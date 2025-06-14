"""Stable error envelope and exception handlers.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "correlation_id": "...", "details": {...}}}

Domain errors map to HTTP statuses here and nowhere else.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from corebank.domain import exceptions as dx
from corebank.logging import correlation_id_var

logger = logging.getLogger("corebank.api")

STATUS_BY_CODE: dict[str, int] = {
    dx.ValidationError.code: status.HTTP_422_UNPROCESSABLE_CONTENT,
    dx.UnsupportedCurrencyError.code: status.HTTP_422_UNPROCESSABLE_CONTENT,
    dx.InvalidAmountError.code: status.HTTP_422_UNPROCESSABLE_CONTENT,
    dx.MissingIdempotencyKeyError.code: status.HTTP_400_BAD_REQUEST,
    dx.CurrencyMismatchError.code: status.HTTP_422_UNPROCESSABLE_CONTENT,
    dx.UnbalancedJournalError.code: status.HTTP_422_UNPROCESSABLE_CONTENT,
    dx.InvalidTransferError.code: status.HTTP_422_UNPROCESSABLE_CONTENT,
    dx.AccountNotFoundError.code: status.HTTP_404_NOT_FOUND,
    dx.JournalNotFoundError.code: status.HTTP_404_NOT_FOUND,
    dx.AccountClosedError.code: status.HTTP_409_CONFLICT,
    dx.AccountFrozenError.code: status.HTTP_409_CONFLICT,
    dx.AccountNotEmptyError.code: status.HTTP_409_CONFLICT,
    dx.InvalidStatusTransitionError.code: status.HTTP_409_CONFLICT,
    dx.InsufficientFundsError.code: status.HTTP_409_CONFLICT,
    dx.JournalNotPostedError.code: status.HTTP_409_CONFLICT,
    dx.JournalAlreadyReversedError.code: status.HTTP_409_CONFLICT,
    dx.ImmutablePostingError.code: status.HTTP_409_CONFLICT,
    dx.IdempotencyConflictError.code: status.HTTP_409_CONFLICT,
    dx.ConcurrencyConflictError.code: status.HTTP_409_CONFLICT,
}


def error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": correlation_id_var.get() or "",
    }
    if details:
        body["details"] = details
    return {"error": body}


def _json(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    # The correlation id header is added by CorrelationIdMiddleware.
    return JSONResponse(status_code=status_code, content=error_payload(code, message, details))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(dx.DomainError)
    async def _domain_error(_: Request, exc: dx.DomainError) -> JSONResponse:
        status_code = STATUS_BY_CODE.get(exc.code, status.HTTP_400_BAD_REQUEST)
        logger.info("domain error", extra={"code": exc.code, "status": status_code})
        return _json(status_code, exc.code, exc.message, exc.details or None)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # A domain validation error raised inside a pydantic validator keeps its code.
        for err in exc.errors():
            cause = (err.get("ctx") or {}).get("error")
            if isinstance(cause, dx.DomainError):
                status_code = STATUS_BY_CODE.get(cause.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
                details = dict(cause.details)
                details["loc"] = [str(part) for part in err.get("loc", ())]
                return _json(status_code, cause.code, cause.message, details)
        errors = [
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return _json(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "The request is invalid.",
            {"errors": errors},
        )

    @app.exception_handler(OperationalError)
    async def _db_unavailable(_: Request, exc: OperationalError) -> JSONResponse:
        logger.error("database unavailable", exc_info=exc)
        return _json(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            "The ledger database is unavailable.",
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        # Never leak internals to the client.
        return _json(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred.",
        )
