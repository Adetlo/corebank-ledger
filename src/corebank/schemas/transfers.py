from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from corebank.domain.ledger import JournalStatus
from corebank.domain.money import validate_currency
from corebank.schemas.common import AmountMixin, AmountStr, APIModel, ResponseModel
from corebank.schemas.journal import JournalEntryResponse


class TransferCreate(AmountMixin, APIModel):
    source_account_id: UUID
    destination_account_id: UUID
    currency: str = Field(min_length=3, max_length=3, examples=["GBP"])
    reference: str = Field(min_length=1, max_length=64, examples=["TRF-DEMO-0001"])
    value_date: date | None = Field(default=None, examples=["2026-10-13"])
    booking_date: date | None = Field(
        default=None, description="Defaults to today (UTC) when omitted."
    )
    description: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency(value)


class TransferResponse(ResponseModel):
    transfer_id: UUID = Field(description="Equal to the id of the journal entry that booked it")
    reference: str
    status: JournalStatus
    source_account_id: UUID
    destination_account_id: UUID
    amount: AmountStr
    currency: str
    booking_date: date
    value_date: date | None
    journal_entry: JournalEntryResponse
