"""ISO 20022-inspired simplified payment model.

**This is not ISO 20022.** It borrows a handful of concept names from the
``pain.001`` customer credit transfer initiation message (``PmtId``,
``EndToEndId``, ``DbtrAcct``, ``CdtrAcct``, ``InstdAmt``, ``ReqdExctnDt``) to
show how an external payment instruction is adapted into an internal ledger
transfer. No schema validation against the ISO XSDs, no message envelopes,
no compliance is claimed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from corebank.domain.money import Money, validate_currency
from corebank.domain.transactions import TransferCommand
from corebank.schemas.common import AmountMixin, APIModel

MODEL_LABEL = "ISO 20022-inspired simplified model"


class PaymentInstruction(AmountMixin, APIModel):
    """Simplified customer credit transfer instruction."""

    payment_id: str = Field(min_length=1, max_length=35, examples=["PMT-2026-000123"])
    end_to_end_id: str = Field(min_length=1, max_length=35, examples=["E2E-INV-55821"])
    debtor_account: UUID = Field(description="Internal ledger account id of the payer")
    creditor_account: UUID = Field(description="Internal ledger account id of the payee")
    currency: str = Field(min_length=3, max_length=3, examples=["GBP"])
    requested_execution_date: date | None = Field(default=None, examples=["2026-10-13"])
    remittance_information: str | None = Field(
        default=None, max_length=140, examples=["Invoice 55821"]
    )

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency(value)

    def to_transfer_command(self, *, booking_date: date | None = None) -> TransferCommand:
        """Adapt the external instruction into an internal transfer command."""
        today = booking_date or datetime.now(UTC).date()
        metadata: dict[str, Any] = {
            "source_model": MODEL_LABEL,
            "payment_id": self.payment_id,
            "end_to_end_id": self.end_to_end_id,
        }
        if self.remittance_information:
            metadata["remittance_information"] = self.remittance_information
        return TransferCommand(
            source_account_id=self.debtor_account,
            destination_account_id=self.creditor_account,
            money=Money(self.amount, self.currency),
            reference=self.end_to_end_id,
            booking_date=today,
            value_date=self.requested_execution_date or today,
            description=self.remittance_information or f"Payment {self.payment_id}",
            metadata=metadata,
        )
