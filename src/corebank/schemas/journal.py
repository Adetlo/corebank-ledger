from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from corebank.domain.ledger import MAX_POSTINGS, Direction, JournalStatus
from corebank.domain.money import validate_currency
from corebank.schemas.common import AmountMixin, AmountStr, APIModel, ResponseModel


class PostingCreate(AmountMixin, APIModel):
    account_id: UUID
    direction: Direction = Field(examples=["DEBIT"])
    currency: str = Field(min_length=3, max_length=3, examples=["GBP"])

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency(value)


class JournalEntryCreate(APIModel):
    reference: str = Field(min_length=1, max_length=64, examples=["DEP-DEMO-0001"])
    description: str = Field(default="", max_length=500, examples=["Synthetic deposit"])
    booking_date: date = Field(examples=["2026-10-13"])
    value_date: date | None = Field(default=None, examples=["2026-10-13"])
    postings: list[PostingCreate] = Field(min_length=2, max_length=MAX_POSTINGS)
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional free-form, non-sensitive metadata (max 20 keys).",
    )

    @model_validator(mode="after")
    def _limit_metadata(self) -> JournalEntryCreate:
        if self.metadata and len(self.metadata) > 20:
            raise ValueError("metadata may contain at most 20 keys")
        return self


class ReversalCreate(APIModel):
    reason: str | None = Field(default=None, max_length=200, examples=["Fee charged in error"])
    reference: str | None = Field(default=None, min_length=1, max_length=64)
    booking_date: date | None = None


class PostingResponse(ResponseModel):
    id: UUID
    journal_entry_id: UUID | None
    account_id: UUID
    direction: Direction
    amount: AmountStr
    currency: str
    created_at: datetime


class JournalEntryResponse(ResponseModel):
    id: UUID
    reference: str
    description: str
    booking_date: date
    value_date: date | None
    status: JournalStatus
    currency: str | None
    total_debits: AmountStr
    total_credits: AmountStr
    postings: list[PostingResponse]
    idempotency_key: str | None
    metadata: dict[str, Any]
    reversal_of: UUID | None
    reversed_by: UUID | None
    created_at: datetime
    posted_at: datetime | None


class AuditEventResponse(ResponseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    event_type: str
    occurred_at: datetime
    correlation_id: str
    actor: str | None
    metadata: dict[str, Any]
