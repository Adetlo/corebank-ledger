"""Properties: reversal restores balances; idempotent replay never adds postings."""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from corebank.application.account_service import AccountService, CreateAccountCommand
from corebank.application.context import RequestContext
from corebank.application.posting_service import PostingLine, PostingService, PostJournalCommand
from corebank.application.reversal_service import ReversalService, ReverseJournalCommand
from corebank.application.transfer_service import TransferService
from corebank.domain.accounts import AccountType
from corebank.domain.ledger import Direction
from corebank.domain.money import Money
from corebank.domain.transactions import TransferCommand
from tests.integration.conftest import TODAY

CTX = RequestContext(correlation_id="hypothesis", actor="property-test")
pence = st.integers(min_value=1, max_value=10**6).map(lambda n: Decimal(n) / 100)


def setup_customers(uow_factory, opening: Decimal):  # type: ignore[no-untyped-def]
    accounts = AccountService(uow_factory())
    settlement = accounts.create_account(
        CreateAccountCommand("Settlement", AccountType.ASSET, "GBP"), CTX
    )
    a = accounts.create_account(CreateAccountCommand("A", AccountType.LIABILITY, "GBP"), CTX)
    b = accounts.create_account(CreateAccountCommand("B", AccountType.LIABILITY, "GBP"), CTX)
    c = accounts.create_account(
        CreateAccountCommand("C (unrelated)", AccountType.LIABILITY, "GBP"), CTX
    )
    PostingService(uow_factory()).post_journal(
        PostJournalCommand(
            reference="OPEN",
            description="",
            booking_date=TODAY,
            postings=[
                PostingLine(settlement.id, Direction.DEBIT, opening * 2, "GBP"),
                PostingLine(a.id, Direction.CREDIT, opening, "GBP"),
                PostingLine(c.id, Direction.CREDIT, opening, "GBP"),
            ],
        ),
        CTX,
        idempotency_key=str(uuid.uuid4()),
    )
    return accounts, settlement, a, b, c


def balances(accounts, *ids):  # type: ignore[no-untyped-def]
    return tuple(accounts.get_balance(i).balance.amount for i in ids)


@given(opening=pence, amount=pence, noise=st.lists(pence, max_size=3))
@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_transfer_then_reversal_restores_balances(
    uow_factory, opening: Decimal, amount: Decimal, noise: list[Decimal]
) -> None:  # type: ignore[no-untyped-def]
    accounts, _settlement, a, b, c = setup_customers(uow_factory, opening)
    transfers = TransferService(uow_factory())
    before = balances(accounts, a.id, b.id)
    if amount > opening:
        amount = opening  # keep the transfer fundable; insufficient funds is tested elsewhere
    result = transfers.transfer(
        TransferCommand(a.id, b.id, Money(amount, "GBP"), "T", TODAY),
        CTX,
        idempotency_key=str(uuid.uuid4()),
    )
    # Unrelated activity between the transfer and its reversal (C -> settlement-funded D is not
    # a transfer, so use C -> B spends and new funding of C).
    noise_total = Decimal(0)
    for extra in noise:
        if (
            extra <= opening - noise_total
        ):  # keep C fundable; insufficient funds is tested elsewhere
            transfers.transfer(
                TransferCommand(c.id, b.id, Money(extra, "GBP"), "N", TODAY),
                CTX,
                idempotency_key=str(uuid.uuid4()),
            )
            noise_total += extra
    ReversalService(uow_factory()).reverse(
        ReverseJournalCommand(result.journal.id), CTX, idempotency_key=str(uuid.uuid4())
    )
    after = balances(accounts, a.id, b.id)
    assert after[0] == before[0]
    assert after[1] == before[1] + noise_total  # B only reflects the unrelated activity
    assert accounts.get_balance(c.id).balance.amount == opening - noise_total


@given(amount=pence, replays=st.integers(min_value=1, max_value=6))
@settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_replaying_never_increases_posting_count(
    uow_factory, amount: Decimal, replays: int
) -> None:  # type: ignore[no-untyped-def]
    accounts, _settlement, a, b, _c = setup_customers(uow_factory, amount)
    key = str(uuid.uuid4())
    command = TransferCommand(a.id, b.id, Money(amount, "GBP"), "IDEM", TODAY)
    service = TransferService(uow_factory())
    first = service.transfer(command, CTX, idempotency_key=key)
    with uow_factory() as uow:
        baseline = uow.journals.count_postings()
    for _ in range(replays):
        again = service.transfer(command, CTX, idempotency_key=key)
        assert again.replayed and again.journal.id == first.journal.id
        with uow_factory() as uow:
            assert uow.journals.count_postings() == baseline
    assert accounts.get_balance(b.id).balance.amount == amount
