from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, field_validator

from corebank.domain.accounts import AccountStatus, AccountType, NormalBalance
from corebank.domain.money import validate_currency
from corebank.schemas.common import AmountStr, APIModel, ResponseModel


class AccountCreate(APIModel):
    account_name: str = Field(
        min_length=1, max_length=200, examples=["Synthetic Customer Current Account"]
    )
    account_type: AccountType = Field(examples=["LIABILITY"])
    currency: str = Field(min_length=3, max_length=3, examples=["GBP"])
    allow_negative_balance: bool | None = Field(
        default=None,
        description=(
            "Whether the balance may go negative. Defaults to false for LIABILITY accounts "
            "(customer deposits) and true for ledger/control accounts."
        ),
    )

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency(value)


class AccountStatusUpdate(APIModel):
    status: AccountStatus = Field(examples=["FROZEN"])


class AccountResponse(ResponseModel):
    id: UUID
    account_number: str = Field(examples=["SYN-4829103771-5"])
    account_name: str
    account_type: AccountType
    currency: str
    status: AccountStatus
    normal_balance: NormalBalance
    allow_negative_balance: bool
    version: int
    created_at: datetime
    updated_at: datetime


class BalanceResponse(ResponseModel):
    account_id: UUID
    currency: str
    normal_balance: NormalBalance
    debit_total: AmountStr = Field(examples=["1250.00"])
    credit_total: AmountStr = Field(examples=["1000.00"])
    balance: AmountStr = Field(
        description="Net balance in the account's natural sign (see docs/LEDGER_INVARIANTS.md)",
        examples=["250.00"],
    )
    as_of_date: date | None = None
    posting_count: int
