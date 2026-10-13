from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from corebank.domain.money import Money
from corebank.integrations.payment_messages import MODEL_LABEL, PaymentInstruction


def test_instruction_adapts_to_transfer_command() -> None:
    debtor, creditor = uuid4(), uuid4()
    instruction = PaymentInstruction(
        payment_id="PMT-1",
        end_to_end_id="E2E-1",
        debtor_account=debtor,
        creditor_account=creditor,
        amount="12.50",
        currency="gbp",
        requested_execution_date=date(2026, 10, 14),
        remittance_information="Invoice 1",
    )
    command = instruction.to_transfer_command(booking_date=date(2026, 10, 13))
    assert command.source_account_id == debtor
    assert command.destination_account_id == creditor
    assert command.money == Money.of("12.50", "GBP")
    assert command.reference == "E2E-1"
    assert command.booking_date == date(2026, 10, 13)
    assert command.value_date == date(2026, 10, 14)
    assert command.description == "Invoice 1"
    assert command.metadata["source_model"] == MODEL_LABEL
    assert command.metadata["payment_id"] == "PMT-1"


def test_defaults_when_optional_fields_missing() -> None:
    instruction = PaymentInstruction(
        payment_id="PMT-2",
        end_to_end_id="E2E-2",
        debtor_account=uuid4(),
        creditor_account=uuid4(),
        amount="1",
        currency="JPY",
    )
    command = instruction.to_transfer_command()
    assert command.value_date == command.booking_date
    assert command.description == "Payment PMT-2"
    assert "remittance_information" not in command.metadata


def test_invalid_currency_and_float_rejected() -> None:
    with pytest.raises(ValidationError):
        PaymentInstruction(
            payment_id="P",
            end_to_end_id="E",
            debtor_account=uuid4(),
            creditor_account=uuid4(),
            amount="1",
            currency="XXX",
        )
    with pytest.raises(ValidationError):
        PaymentInstruction.model_validate(
            {
                "payment_id": "P",
                "end_to_end_id": "E",
                "debtor_account": str(uuid4()),
                "creditor_account": str(uuid4()),
                "amount": 1.5,
                "currency": "GBP",
            }
        )
