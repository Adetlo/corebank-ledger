"""Critical property: any balanced journal entry posts with SUM(debits) == SUM(credits)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from corebank.application.account_service import AccountService, CreateAccountCommand
from corebank.application.context import RequestContext
from corebank.application.posting_service import PostingLine, PostingService, PostJournalCommand
from corebank.application.reconciliation_service import ReconciliationService
from corebank.domain.accounts import AccountType
from corebank.domain.exceptions import UnbalancedJournalError
from corebank.domain.ledger import Direction, Posting, validate_balanced
from corebank.domain.money import Money, quantum
from tests.integration.conftest import TODAY

CTX = RequestContext(correlation_id="hypothesis", actor="property-test")


@st.composite
def balanced_legs(
    draw, currency: str = "GBP", max_legs: int = 6
) -> list[tuple[Direction, Decimal]]:  # type: ignore[no-untyped-def]
    """Random positive amounts on both sides, then a final leg that forces balance."""
    q = quantum(currency)
    n_debits = draw(st.integers(min_value=1, max_value=max_legs))
    n_credits = draw(st.integers(min_value=1, max_value=max_legs))
    units = st.integers(min_value=1, max_value=10**9)
    debits = [Decimal(draw(units)) * q for _ in range(n_debits)]
    credits = [Decimal(draw(units)) * q for _ in range(n_credits)]
    diff = sum(debits) - sum(credits)
    if diff > 0:
        credits.append(diff)
    elif diff < 0:
        debits.append(-diff)
    legs = [(Direction.DEBIT, d) for d in debits] + [(Direction.CREDIT, c) for c in credits]
    return draw(st.permutations(legs))


@given(balanced_legs())
@settings(max_examples=150)
def test_domain_accepts_every_balanced_set(legs: list[tuple[Direction, Decimal]]) -> None:
    postings = [Posting(uuid.uuid4(), d, Money(a, "GBP")) for d, a in legs]
    check = validate_balanced(postings)
    assert check.balanced
    assert check.total_debits == check.total_credits


@given(balanced_legs(), st.integers(min_value=1, max_value=10**6))
@settings(max_examples=100)
def test_domain_rejects_every_perturbation(
    legs: list[tuple[Direction, Decimal]], delta: int
) -> None:
    direction, amount = legs[0]
    perturbed = [(direction, amount + Decimal(delta) * quantum("GBP")), *legs[1:]]
    postings = [Posting(uuid.uuid4(), d, Money(a, "GBP")) for d, a in perturbed]
    try:
        validate_balanced(postings)
    except UnbalancedJournalError:
        return
    raise AssertionError("perturbed entry must be rejected")


@given(balanced_legs(max_legs=4))
@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_posted_entries_balance_in_the_database(
    uow_factory, legs: list[tuple[Direction, Decimal]]
) -> None:  # type: ignore[no-untyped-def]
    accounts = AccountService(uow_factory())
    # Ledger accounts that may swing negative, so only the balancing rule is under test.
    ids = [
        accounts.create_account(CreateAccountCommand(f"Prop {i}", AccountType.ASSET, "GBP"), CTX).id
        for i in range(len(legs))
    ]
    command = PostJournalCommand(
        reference=f"PROP-{uuid.uuid4().hex[:8]}",
        description="property",
        booking_date=TODAY,
        postings=[PostingLine(ids[i], d, a, "GBP") for i, (d, a) in enumerate(legs)],
    )
    result = PostingService(uow_factory()).post_journal(
        command, CTX, idempotency_key=str(uuid.uuid4())
    )
    with uow_factory() as uow:
        stored = uow.journals.get(result.journal.id)
    assert stored is not None
    debits = sum(p.money.amount for p in stored.postings if p.direction is Direction.DEBIT)
    credits = sum(p.money.amount for p in stored.postings if p.direction is Direction.CREDIT)
    assert debits == credits
    check = ReconciliationService(uow_factory()).ledger_check()
    assert check.balanced and not check.unbalanced_journal_ids
