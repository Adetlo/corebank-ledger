"""Higher-level transaction types expressed as journal entries.

A *transfer* means "value moves from the source account to the destination
account": the source balance decreases and the destination balance increases,
each in its own natural sign. The posting direction therefore depends on the
accounts' normal balances:

* decreasing an account = posting on the side **opposite** its normal balance
* increasing an account = posting on the **same** side as its normal balance

For two customer deposit accounts (LIABILITY, credit-normal) this yields the
textbook ``DEBIT source / CREDIT destination``. For two asset accounts (e.g.
moving cash between settlement accounts) it yields ``CREDIT source / DEBIT
destination``. A transfer from a customer account to a fee-income account
(both credit-normal) yields ``DEBIT customer / CREDIT income``.

If the two accounts have *different* normal balances the pair of postings
cannot balance (both legs would land on the same side). Such movements, for
example funding a customer account from a settlement asset, are *not*
transfers but deposits/withdrawals and must be booked as explicit journal
entries. The service raises :class:`InvalidTransferError` in that case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from corebank.domain.accounts import Account, NormalBalance
from corebank.domain.exceptions import CurrencyMismatchError, InvalidTransferError
from corebank.domain.ledger import Direction, JournalEntry, Posting
from corebank.domain.money import Money


def direction_to_increase(normal_balance: NormalBalance) -> Direction:
    return Direction.DEBIT if normal_balance is NormalBalance.DEBIT else Direction.CREDIT


def direction_to_decrease(normal_balance: NormalBalance) -> Direction:
    return direction_to_increase(normal_balance).opposite


@dataclass(frozen=True, slots=True)
class TransferCommand:
    source_account_id: UUID
    destination_account_id: UUID
    money: Money
    reference: str
    booking_date: date
    value_date: date | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def build_transfer_journal(
    command: TransferCommand,
    source: Account,
    destination: Account,
    *,
    idempotency_key: str | None = None,
) -> JournalEntry:
    """Translate a transfer into a balanced two-leg journal entry."""
    if source.id == destination.id:
        raise InvalidTransferError(
            "Source and destination accounts must differ.", account_id=str(source.id)
        )
    if not command.money.is_positive:
        raise InvalidTransferError("Transfer amount must be positive.")
    for account in (source, destination):
        if account.currency != command.money.currency:
            raise CurrencyMismatchError(
                f"Account {account.account_number} is denominated in {account.currency}, "
                f"transfer is in {command.money.currency}.",
                account_id=str(account.id),
                account_currency=account.currency,
                transfer_currency=command.money.currency,
            )
    if source.normal_balance is not destination.normal_balance:
        raise InvalidTransferError(
            "A transfer requires both accounts to share the same normal balance "
            f"(source is {source.normal_balance}-normal, destination is "
            f"{destination.normal_balance}-normal). Book this movement as a journal entry.",
            source_normal_balance=source.normal_balance,
            destination_normal_balance=destination.normal_balance,
        )
    postings = [
        Posting(
            account_id=source.id,
            direction=direction_to_decrease(source.normal_balance),
            money=command.money,
        ),
        Posting(
            account_id=destination.id,
            direction=direction_to_increase(destination.normal_balance),
            money=command.money,
        ),
    ]
    metadata: dict[str, Any] = {
        "kind": "TRANSFER",
        "source_account_id": str(source.id),
        "destination_account_id": str(destination.id),
        **command.metadata,
    }
    return JournalEntry(
        reference=command.reference,
        description=command.description
        or f"Transfer {command.money} from {source.account_number} to {destination.account_number}",
        booking_date=command.booking_date,
        value_date=command.value_date or command.booking_date,
        postings=postings,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )
