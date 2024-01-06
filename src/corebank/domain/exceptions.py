"""Domain exceptions with stable, machine-readable error codes.

Every error raised from the domain or application layer carries a ``code``
that the API layer maps to an HTTP status and renders in a stable envelope::

    {"error": {"code": "UNBALANCED_JOURNAL", "message": "...", "correlation_id": "..."}}

Codes are part of the public contract and must not be renamed casually.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for all ledger domain errors."""

    code: str = "DOMAIN_ERROR"
    message: str = "A domain rule was violated."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.__class__.message
        self.details: dict[str, Any] = details
        super().__init__(self.message)


class ValidationError(DomainError, ValueError):
    """Also a ``ValueError`` so pydantic validators can raise it; the API layer
    unwraps it again to keep the specific error code (e.g. UNSUPPORTED_CURRENCY)."""

    code = "VALIDATION_ERROR"
    message = "The request is invalid."


class UnsupportedCurrencyError(ValidationError):
    code = "UNSUPPORTED_CURRENCY"
    message = "The currency is not supported by this ledger."


class InvalidAmountError(ValidationError):
    code = "INVALID_AMOUNT"
    message = "The amount is invalid for this currency."


class CurrencyMismatchError(DomainError):
    code = "CURRENCY_MISMATCH"
    message = "All postings and accounts in a journal entry must share one currency."


class UnbalancedJournalError(DomainError):
    code = "UNBALANCED_JOURNAL"
    message = "Journal entry debits and credits must balance."


class AccountNotFoundError(DomainError):
    code = "ACCOUNT_NOT_FOUND"
    message = "The account does not exist."


class AccountClosedError(DomainError):
    code = "ACCOUNT_CLOSED"
    message = "The account is closed and cannot accept postings."


class AccountFrozenError(DomainError):
    code = "ACCOUNT_FROZEN"
    message = "The account is frozen and cannot accept postings."


class AccountNotEmptyError(DomainError):
    code = "ACCOUNT_NOT_EMPTY"
    message = "An account with a non-zero balance cannot be closed."


class InvalidStatusTransitionError(DomainError):
    code = "INVALID_STATUS_TRANSITION"
    message = "The requested account status transition is not allowed."


class InsufficientFundsError(DomainError):
    code = "INSUFFICIENT_FUNDS"
    message = "The account does not have sufficient available funds."


class JournalNotFoundError(DomainError):
    code = "JOURNAL_NOT_FOUND"
    message = "The journal entry does not exist."


class JournalNotPostedError(DomainError):
    code = "JOURNAL_NOT_POSTED"
    message = "Only POSTED journal entries can be reversed."


class JournalAlreadyReversedError(DomainError):
    code = "JOURNAL_ALREADY_REVERSED"
    message = "The journal entry has already been reversed."


class ImmutablePostingError(DomainError):
    code = "IMMUTABLE_POSTING"
    message = "Posted journal entries and their postings are immutable."


class IdempotencyConflictError(DomainError):
    code = "IDEMPOTENCY_CONFLICT"
    message = "The Idempotency-Key was already used with a different request payload."


class MissingIdempotencyKeyError(ValidationError):
    code = "MISSING_IDEMPOTENCY_KEY"
    message = "An Idempotency-Key header is required for this operation."


class InvalidTransferError(DomainError):
    code = "INVALID_TRANSFER"
    message = "The transfer cannot be expressed as a balanced journal entry."


class ConcurrencyConflictError(DomainError):
    code = "CONCURRENCY_CONFLICT"
    message = "The operation conflicted with a concurrent update; please retry."
