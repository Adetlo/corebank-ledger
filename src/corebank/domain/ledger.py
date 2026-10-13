"""Journal entries and postings: the double-entry core.

The **absolute ledger invariant** lives here, in :func:`validate_balanced`:

    for every POSTED journal entry, SUM(debits) == SUM(credits)

It is enforced in the domain (this module), re-checked by the application
layer before the database transaction commits, and reinforced by a deferred
constraint trigger in PostgreSQL (see ``migrations/``). API validation is a
convenience on top, never the only line of defence.

Immutability
------------
``Posting`` is a frozen dataclass: amount, account and direction cannot be
edited once constructed. A ``JournalEntry`` refuses structural changes once
it is POSTED (:class:`ImmutablePostingError`). Corrections are made by
posting a reversal (:meth:`JournalEntry.build_reversal`), never by editing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from corebank.domain.exceptions import (
    CurrencyMismatchError,
    ImmutablePostingError,
    InvalidAmountError,
    JournalAlreadyReversedError,
    JournalNotPostedError,
    UnbalancedJournalError,
)
from corebank.domain.money import Money, sum_money


class Direction(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

    @property
    def opposite(self) -> Direction:
        return Direction.CREDIT if self is Direction.DEBIT else Direction.DEBIT


class JournalStatus(StrEnum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    FAILED = "FAILED"


#: Statuses whose postings contribute to balances. A REVERSED entry's postings
#: still count: they are offset by the reversal entry, preserving history.
EFFECTIVE_STATUSES: frozenset[JournalStatus] = frozenset(
    {JournalStatus.POSTED, JournalStatus.REVERSED}
)

MIN_POSTINGS = 2
MAX_POSTINGS = 1000


@dataclass(frozen=True, slots=True)
class Posting:
    """One leg of a journal entry. Immutable by construction."""

    account_id: UUID
    direction: Direction
    money: Money
    id: UUID = field(default_factory=uuid4)
    journal_entry_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", Direction(self.direction))
        if not self.money.is_positive:
            raise InvalidAmountError(
                "Posting amounts must be strictly positive; use the direction to express sign.",
                amount=self.money.as_string(),
            )

    @property
    def amount(self) -> Money:
        return self.money

    @property
    def currency(self) -> str:
        return self.money.currency

    def reversed(self) -> Posting:
        """A new posting of equal amount on the opposite side."""
        return Posting(
            account_id=self.account_id, direction=self.direction.opposite, money=self.money
        )


@dataclass(frozen=True, slots=True)
class BalanceCheck:
    currency: str
    total_debits: Money
    total_credits: Money

    @property
    def difference(self) -> Money:
        return self.total_debits - self.total_credits

    @property
    def balanced(self) -> bool:
        return self.difference.is_zero


def summarise(postings: list[Posting] | tuple[Posting, ...]) -> BalanceCheck:
    """Totals for a set of single-currency postings."""
    if not postings:
        raise UnbalancedJournalError("A journal entry requires at least two postings.")
    currency = postings[0].currency
    for posting in postings:
        if posting.currency != currency:
            raise CurrencyMismatchError(
                "All postings in a journal entry must share one currency.",
                expected=currency,
                actual=posting.currency,
            )
    debits = sum_money([p.money for p in postings if p.direction is Direction.DEBIT], currency)
    credits = sum_money([p.money for p in postings if p.direction is Direction.CREDIT], currency)
    return BalanceCheck(currency=currency, total_debits=debits, total_credits=credits)


def validate_balanced(postings: list[Posting] | tuple[Posting, ...]) -> BalanceCheck:
    """THE ledger invariant. Raise unless SUM(debits) == SUM(credits).

    Also enforces: at least two postings, at most ``MAX_POSTINGS``, a single
    currency, and at least one posting on each side.
    """
    if len(postings) < MIN_POSTINGS:
        raise UnbalancedJournalError(
            f"A journal entry requires at least {MIN_POSTINGS} postings.",
            posting_count=len(postings),
        )
    if len(postings) > MAX_POSTINGS:
        raise UnbalancedJournalError(
            f"A journal entry may contain at most {MAX_POSTINGS} postings.",
            posting_count=len(postings),
        )
    check = summarise(postings)
    if check.total_debits.is_zero or check.total_credits.is_zero:
        raise UnbalancedJournalError(
            "A journal entry needs at least one debit and one credit posting.",
            total_debits=check.total_debits.as_string(),
            total_credits=check.total_credits.as_string(),
        )
    if not check.balanced:
        raise UnbalancedJournalError(
            "Journal entry debits and credits must balance.",
            currency=check.currency,
            total_debits=check.total_debits.as_string(),
            total_credits=check.total_credits.as_string(),
            difference=check.difference.as_string(),
        )
    return check


@dataclass(slots=True)
class JournalEntry:
    """One accounting transaction made of balanced postings."""

    reference: str
    description: str
    booking_date: date
    value_date: date | None = None
    postings: list[Posting] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    status: JournalStatus = JournalStatus.PENDING
    currency: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    reversal_of: UUID | None = None
    reversed_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    posted_at: datetime | None = None

    def __post_init__(self) -> None:
        self.status = JournalStatus(self.status)
        if self.value_date is None:
            self.value_date = self.booking_date
        reference = self.reference.strip()
        if not reference:
            raise ValueError("reference must not be blank")
        self.reference = reference
        # Bind postings to this journal and derive the currency.
        bound: list[Posting] = []
        for posting in self.postings:
            bound.append(self._bind(posting))
        self.postings = bound
        if bound and self.currency is None:
            self.currency = bound[0].currency

    # ----- state predicates --------------------------------------------------
    @property
    def is_posted(self) -> bool:
        return self.status is JournalStatus.POSTED

    @property
    def is_effective(self) -> bool:
        return self.status in EFFECTIVE_STATUSES

    @property
    def is_immutable(self) -> bool:
        return self.status in EFFECTIVE_STATUSES

    @property
    def is_reversal(self) -> bool:
        return self.reversal_of is not None

    def _bind(self, posting: Posting) -> Posting:
        if posting.journal_entry_id == self.id:
            return posting
        return Posting(
            id=posting.id,
            journal_entry_id=self.id,
            account_id=posting.account_id,
            direction=posting.direction,
            money=posting.money,
            created_at=posting.created_at,
        )

    # ----- mutation guarded by immutability ----------------------------------
    def add_posting(self, posting: Posting) -> None:
        if self.is_immutable:
            raise ImmutablePostingError(journal_entry_id=str(self.id), status=self.status)
        self.postings.append(self._bind(posting))
        if self.currency is None:
            self.currency = posting.currency

    def balance_check(self) -> BalanceCheck:
        return validate_balanced(self.postings)

    def post(self, *, posted_at: datetime | None = None) -> BalanceCheck:
        """Transition PENDING -> POSTED after proving the invariant holds."""
        if self.status is not JournalStatus.PENDING:
            raise ImmutablePostingError(
                f"Journal entry is {self.status} and cannot be posted again.",
                journal_entry_id=str(self.id),
            )
        check = validate_balanced(self.postings)
        self.currency = check.currency
        self.status = JournalStatus.POSTED
        self.posted_at = posted_at or datetime.now(UTC)
        return check

    def fail(self) -> None:
        if self.is_immutable:
            raise ImmutablePostingError(journal_entry_id=str(self.id), status=self.status)
        self.status = JournalStatus.FAILED

    # ----- reversal ------------------------------------------------------------
    def build_reversal(
        self,
        *,
        reference: str | None = None,
        description: str | None = None,
        booking_date: date | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> JournalEntry:
        """Create (but do not persist) the entry that reverses this one.

        The original stays untouched here; the application layer links
        ``reversed_by`` inside the same database transaction that posts the
        reversal, so the two can never disagree.
        """
        if self.status is JournalStatus.REVERSED or self.reversed_by is not None:
            raise JournalAlreadyReversedError(
                journal_entry_id=str(self.id), reversed_by=str(self.reversed_by)
            )
        if self.status is not JournalStatus.POSTED:
            raise JournalNotPostedError(journal_entry_id=str(self.id), status=self.status)
        if self.is_reversal:
            # Reversing a reversal is a legitimate correction, but it must be a
            # fresh entry rather than "un-reversing" the original.
            pass
        metadata: dict[str, Any] = {"reversal_reason": reason} if reason else {}
        return JournalEntry(
            reference=reference or f"REV-{self.reference}",
            description=description or f"Reversal of {self.reference}: {self.description}",
            booking_date=booking_date or datetime.now(UTC).date(),
            value_date=booking_date or datetime.now(UTC).date(),
            postings=[p.reversed() for p in self.postings],
            currency=self.currency,
            idempotency_key=idempotency_key,
            metadata=metadata,
            reversal_of=self.id,
        )

    def mark_reversed(self, reversal_id: UUID) -> None:
        """Link the reversal. Postings remain untouched; only lineage changes."""
        if self.reversed_by is not None or self.status is JournalStatus.REVERSED:
            raise JournalAlreadyReversedError(journal_entry_id=str(self.id))
        if self.status is not JournalStatus.POSTED:
            raise JournalNotPostedError(journal_entry_id=str(self.id), status=self.status)
        self.reversed_by = reversal_id
        self.status = JournalStatus.REVERSED
