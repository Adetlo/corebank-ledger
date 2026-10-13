"""Service-level fixtures: a seeded chart of accounts for integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from corebank.application.account_service import AccountService, CreateAccountCommand
from corebank.application.context import RequestContext
from corebank.application.posting_service import PostingLine, PostingService, PostJournalCommand
from corebank.domain.accounts import Account, AccountType
from corebank.domain.ledger import Direction

TODAY = date(2026, 10, 13)


@dataclass
class Ledger:
    settlement: Account
    customer_a: Account
    customer_b: Account
    fee_income: Account
    expense: Account
    suspense: Account


@pytest.fixture
def ctx() -> RequestContext:
    return RequestContext(correlation_id="test-correlation", actor="pytest")


@pytest.fixture
def ledger(uow_factory, ctx) -> Ledger:  # type: ignore[no-untyped-def]
    service = AccountService(uow_factory())

    def make(name: str, kind: AccountType, allow_negative: bool | None = None) -> Account:
        return service.create_account(
            CreateAccountCommand(name, kind, "GBP", allow_negative_balance=allow_negative), ctx
        )

    return Ledger(
        settlement=make("Cash / Settlement GBP", AccountType.ASSET),
        customer_a=make("Synthetic Customer A", AccountType.LIABILITY),
        customer_b=make("Synthetic Customer B", AccountType.LIABILITY),
        fee_income=make("Fee Income", AccountType.INCOME),
        expense=make("Operating Expense", AccountType.EXPENSE),
        suspense=make("Suspense Account", AccountType.LIABILITY, allow_negative=True),
    )


def journal_command(
    lines: list[tuple[UUID, Direction, str]],
    *,
    reference: str = "JRN-1",
    currency: str = "GBP",
    booking_date: date = TODAY,
) -> PostJournalCommand:
    return PostJournalCommand(
        reference=reference,
        description="integration test",
        booking_date=booking_date,
        postings=[PostingLine(a, d, Decimal(amt), currency) for a, d, amt in lines],
    )


@pytest.fixture
def post(uow_factory, ctx):  # type: ignore[no-untyped-def]
    """Callable: post(lines, reference=..., key=...) -> PostResult."""

    def _post(lines, *, reference="JRN-1", key=None, currency="GBP", booking_date=TODAY):  # type: ignore[no-untyped-def]
        import uuid

        service = PostingService(uow_factory())
        return service.post_journal(
            journal_command(
                lines, reference=reference, currency=currency, booking_date=booking_date
            ),
            ctx,
            idempotency_key=key or f"k-{uuid.uuid4()}",
        )

    return _post


@pytest.fixture
def fund(post, ledger):  # type: ignore[no-untyped-def]
    """Fund a customer account from the settlement asset (deposit)."""

    def _fund(account: Account, amount: str):  # type: ignore[no-untyped-def]
        import uuid

        return post(
            [
                (ledger.settlement.id, Direction.DEBIT, amount),
                (account.id, Direction.CREDIT, amount),
            ],
            reference=f"FUND-{uuid.uuid4().hex[:6]}",
        )

    return _fund
