from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from corebank.domain.accounts import NormalBalance
from corebank.schemas.common import AmountStr, ResponseModel


class TrialBalanceLineResponse(ResponseModel):
    account_id: UUID
    account_number: str
    account_name: str
    account_type: str
    normal_balance: NormalBalance
    currency: str
    debit_total: AmountStr
    credit_total: AmountStr
    net_balance: AmountStr


class TrialBalanceResponse(ResponseModel):
    currency: str = Field(examples=["GBP"])
    as_of_date: date | None
    accounts: list[TrialBalanceLineResponse]
    total_debits: AmountStr = Field(examples=["125000.00"])
    total_credits: AmountStr = Field(examples=["125000.00"])
    difference: AmountStr = Field(examples=["0.00"])
    balanced: bool = Field(examples=[True])


class LedgerCheckLineResponse(ResponseModel):
    currency: str
    total_debits: AmountStr
    total_credits: AmountStr
    difference: AmountStr
    balanced: bool
    posting_count: int


class LedgerCheckResponse(ResponseModel):
    as_of_date: date | None
    balanced: bool
    currencies: list[LedgerCheckLineResponse]
    unbalanced_journal_ids: list[UUID]
