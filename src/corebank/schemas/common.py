from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from corebank.domain.exceptions import InvalidAmountError
from corebank.domain.money import to_decimal

#: Decimal rendered as a plain string in JSON output.
AmountStr = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str)]


def parse_amount(value: Any) -> Decimal:
    """Accept str/int/Decimal; reject floats, NaN/Infinity, junk and non-positive values."""
    if isinstance(value, float):
        raise InvalidAmountError(
            'Amounts must be sent as strings such as "100.00", never as JSON floats.',
            value=repr(value),
        )
    amount = to_decimal(value)
    if amount <= 0:
        raise InvalidAmountError("Amount must be strictly positive.", amount=str(amount))
    return amount


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int = Field(description="Total number of matching records")
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str = Field(examples=["UNBALANCED_JOURNAL"])
    message: str = Field(examples=["Journal entry debits and credits must balance."])
    correlation_id: str = Field(examples=["0f2a1a3c4d5e6f708192a3b4c5d6e7f8"])
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AmountMixin(BaseModel):
    amount: AmountStr = Field(
        description="Decimal amount as a string with at most the currency's minor units",
        examples=["1000.00"],
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: Any) -> Decimal:
        return parse_amount(value)
