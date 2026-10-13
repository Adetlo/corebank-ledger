from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from corebank.domain.exceptions import (
    CurrencyMismatchError,
    ImmutablePostingError,
    InvalidAmountError,
    JournalAlreadyReversedError,
    JournalNotPostedError,
    UnbalancedJournalError,
)
from corebank.domain.ledger import (
    MAX_POSTINGS,
    Direction,
    JournalEntry,
    JournalStatus,
    Posting,
    summarise,
    validate_balanced,
)
from corebank.domain.money import Money

A, B, C = uuid4(), uuid4(), uuid4()
TODAY = date(2026, 10, 13)


def posting(account, direction: str, amount: str, currency: str = "GBP") -> Posting:  # type: ignore[no-untyped-def]
    return Posting(
        account_id=account, direction=Direction(direction), money=Money.of(amount, currency)
    )


def balanced_entry(reference: str = "DEP-1") -> JournalEntry:
    return JournalEntry(
        reference=reference,
        description="deposit",
        booking_date=TODAY,
        postings=[posting(A, "DEBIT", "1000.00"), posting(B, "CREDIT", "1000.00")],
    )


class TestBalancingInvariant:
    def test_balanced_entry_passes(self) -> None:
        check = validate_balanced([posting(A, "DEBIT", "1000.00"), posting(B, "CREDIT", "1000.00")])
        assert check.balanced and check.difference.is_zero

    def test_rejects_999_99_against_1000(self) -> None:
        with pytest.raises(UnbalancedJournalError) as exc:
            validate_balanced([posting(A, "DEBIT", "999.99"), posting(B, "CREDIT", "1000.00")])
        assert exc.value.code == "UNBALANCED_JOURNAL"
        assert exc.value.details["difference"] == "-0.01"

    def test_multi_leg_balanced(self) -> None:
        legs = [
            posting(A, "DEBIT", "100.00"),
            posting(B, "CREDIT", "60.00"),
            posting(C, "CREDIT", "40.00"),
        ]
        assert validate_balanced(legs).balanced

    def test_requires_two_postings(self) -> None:
        with pytest.raises(UnbalancedJournalError):
            validate_balanced([posting(A, "DEBIT", "1.00")])
        with pytest.raises(UnbalancedJournalError):
            validate_balanced([])
        with pytest.raises(UnbalancedJournalError):
            summarise([])

    def test_requires_both_sides(self) -> None:
        with pytest.raises(UnbalancedJournalError):
            validate_balanced([posting(A, "DEBIT", "1.00"), posting(B, "DEBIT", "1.00")])

    def test_single_currency(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            validate_balanced(
                [posting(A, "DEBIT", "1.00", "GBP"), posting(B, "CREDIT", "1.00", "USD")]
            )

    def test_max_postings(self) -> None:
        legs = [posting(uuid4(), "DEBIT", "1.00") for _ in range(MAX_POSTINGS)]
        legs.append(posting(B, "CREDIT", str(MAX_POSTINGS)))
        with pytest.raises(UnbalancedJournalError, match="at most"):
            validate_balanced(legs)

    def test_zero_or_negative_amounts_rejected(self) -> None:
        with pytest.raises(InvalidAmountError):
            posting(A, "DEBIT", "0.00")
        with pytest.raises(InvalidAmountError):
            posting(A, "DEBIT", "-5.00")


class TestJournalLifecycle:
    def test_post_sets_status_and_timestamp(self) -> None:
        entry = balanced_entry()
        assert entry.status is JournalStatus.PENDING
        assert entry.value_date == TODAY
        check = entry.post()
        assert entry.status is JournalStatus.POSTED
        assert entry.posted_at is not None
        assert entry.currency == "GBP"
        assert check.total_debits == Money.of("1000.00", "GBP")
        assert all(p.journal_entry_id == entry.id for p in entry.postings)

    def test_unbalanced_entry_cannot_be_posted(self) -> None:
        entry = JournalEntry(
            reference="X",
            description="",
            booking_date=TODAY,
            postings=[posting(A, "DEBIT", "1.00"), posting(B, "CREDIT", "2.00")],
        )
        with pytest.raises(UnbalancedJournalError):
            entry.post()
        assert entry.status is JournalStatus.PENDING

    def test_blank_reference_rejected(self) -> None:
        with pytest.raises(ValueError, match="reference"):
            JournalEntry(reference="  ", description="", booking_date=TODAY)

    def test_posted_entry_is_immutable(self) -> None:
        entry = balanced_entry()
        entry.post()
        with pytest.raises(ImmutablePostingError):
            entry.add_posting(posting(C, "DEBIT", "1.00"))
        with pytest.raises(ImmutablePostingError):
            entry.post()
        with pytest.raises(ImmutablePostingError):
            entry.fail()
        assert entry.is_immutable and entry.is_effective

    def test_posting_is_frozen(self) -> None:
        p = posting(A, "DEBIT", "1.00")
        with pytest.raises(AttributeError):
            p.direction = Direction.CREDIT  # type: ignore[misc]
        with pytest.raises(AttributeError):
            p.money = Money.of("2", "GBP")  # type: ignore[misc]

    def test_pending_entry_can_fail_and_add_postings(self) -> None:
        entry = JournalEntry(reference="X", description="", booking_date=TODAY)
        entry.add_posting(posting(A, "DEBIT", "1.00"))
        entry.add_posting(posting(B, "CREDIT", "1.00"))
        assert entry.currency == "GBP"
        entry.fail()
        assert entry.status is JournalStatus.FAILED


class TestReversal:
    def test_reversal_has_opposite_postings_and_link(self) -> None:
        entry = balanced_entry()
        entry.post()
        reversal = entry.build_reversal(reason="error")
        assert reversal.reversal_of == entry.id
        assert reversal.reference == "REV-DEP-1"
        assert reversal.metadata == {"reversal_reason": "error"}
        assert reversal.status is JournalStatus.PENDING
        by_account = {p.account_id: p for p in reversal.postings}
        assert by_account[A].direction is Direction.CREDIT
        assert by_account[B].direction is Direction.DEBIT
        assert all(p.money == Money.of("1000.00", "GBP") for p in reversal.postings)
        assert reversal.balance_check().balanced
        # Original untouched by building the reversal.
        assert entry.status is JournalStatus.POSTED and entry.reversed_by is None

    def test_cannot_reverse_pending_entry(self) -> None:
        with pytest.raises(JournalNotPostedError):
            balanced_entry().build_reversal()

    def test_cannot_reverse_twice(self) -> None:
        entry = balanced_entry()
        entry.post()
        reversal = entry.build_reversal()
        entry.mark_reversed(reversal.id)
        assert entry.status is JournalStatus.REVERSED and entry.reversed_by == reversal.id
        with pytest.raises(JournalAlreadyReversedError):
            entry.build_reversal()
        with pytest.raises(JournalAlreadyReversedError):
            entry.mark_reversed(uuid4())

    def test_mark_reversed_requires_posted(self) -> None:
        with pytest.raises(JournalNotPostedError):
            balanced_entry().mark_reversed(uuid4())

    def test_reversed_entry_still_counts_as_effective(self) -> None:
        entry = balanced_entry()
        entry.post()
        entry.mark_reversed(uuid4())
        assert entry.is_effective and entry.is_immutable

    def test_posting_reversed_helper(self) -> None:
        p = posting(A, "DEBIT", "5.00")
        r = p.reversed()
        assert r.direction is Direction.CREDIT and r.money == p.money and r.account_id == A
        assert r.id != p.id
