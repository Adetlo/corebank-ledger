"""Invariant 3: a journal entry posts atomically, or not at all."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from corebank.application import posting_service
from corebank.domain.exceptions import InsufficientFundsError
from corebank.domain.ledger import Direction
from corebank.infrastructure.models import (
    AuditEventModel,
    IdempotencyRecordModel,
    JournalEntryModel,
    PostingModel,
)
from corebank.infrastructure.repositories.audit import AuditEventType, AuditRepository


def table_counts(uow_factory) -> dict[str, int]:  # type: ignore[no-untyped-def]
    with uow_factory() as uow:
        s = uow.session
        return {
            "journals": s.execute(select(func.count(JournalEntryModel.id))).scalar_one(),
            "postings": s.execute(select(func.count(PostingModel.id))).scalar_one(),
            "idempotency": s.execute(select(func.count(IdempotencyRecordModel.id))).scalar_one(),
            "audit": s.execute(
                select(func.count(AuditEventModel.id)).where(
                    AuditEventModel.entity_type == "journal_entry"
                )
            ).scalar_one(),
        }


def test_failure_after_postings_are_written_rolls_everything_back(
    uow_factory, ledger, post, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Simulate a crash *after* journal + postings were flushed but before commit."""
    original_add = AuditRepository.add

    def exploding_add(self, event):  # type: ignore[no-untyped-def]
        if event.event_type is AuditEventType.JOURNAL_POSTED:
            # By now JournalRepository.add has flushed the journal and postings rows.
            n = self._session.execute(select(func.count(PostingModel.id))).scalar_one()
            assert n == 2, "postings should already be flushed inside the open transaction"
            raise RuntimeError("simulated infrastructure failure")
        original_add(self, event)

    monkeypatch.setattr(AuditRepository, "add", exploding_add)
    with pytest.raises(RuntimeError, match="simulated"):
        post(
            [
                (ledger.settlement.id, Direction.DEBIT, "10.00"),
                (ledger.customer_a.id, Direction.CREDIT, "10.00"),
            ]
        )
    assert table_counts(uow_factory) == {"journals": 0, "postings": 0, "idempotency": 0, "audit": 0}


def test_domain_rejection_leaves_no_trace(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(InsufficientFundsError):
        post(
            [
                (ledger.customer_a.id, Direction.DEBIT, "10.00"),
                (ledger.fee_income.id, Direction.CREDIT, "10.00"),
            ]
        )
    assert table_counts(uow_factory) == {"journals": 0, "postings": 0, "idempotency": 0, "audit": 0}


def test_uow_rolls_back_when_commit_not_called(uow_factory, ledger) -> None:  # type: ignore[no-untyped-def]
    from corebank.domain.ledger import JournalEntry, Posting
    from corebank.domain.money import Money
    from tests.integration.conftest import TODAY

    with uow_factory() as uow:
        entry = JournalEntry(
            reference="NO-COMMIT",
            description="",
            booking_date=TODAY,
            postings=[
                Posting(
                    account_id=ledger.settlement.id,
                    direction=Direction.DEBIT,
                    money=Money.of("1", "GBP"),
                ),
                Posting(
                    account_id=ledger.customer_a.id,
                    direction=Direction.CREDIT,
                    money=Money.of("1", "GBP"),
                ),
            ],
        )
        entry.post()
        uow.journals.add(entry)
        # leaving the block without commit() -> rollback
    assert table_counts(uow_factory)["journals"] == 0


class TestDatabaseLevelGuards:
    """The PostgreSQL triggers reinforce the invariants even if application code is bypassed."""

    def test_postings_cannot_be_updated_or_deleted(self, uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
        result = post(
            [
                (ledger.settlement.id, Direction.DEBIT, "10.00"),
                (ledger.customer_a.id, Direction.CREDIT, "10.00"),
            ]
        )
        pid = result.journal.postings[0].id
        with uow_factory() as uow, pytest.raises(DBAPIError, match="IMMUTABLE_POSTING"):
            uow.session.execute(
                text("UPDATE postings SET amount = 999 WHERE id = :id"), {"id": pid}
            )
        with uow_factory() as uow, pytest.raises(DBAPIError, match="IMMUTABLE_POSTING"):
            uow.session.execute(text("DELETE FROM postings WHERE id = :id"), {"id": pid})

    def test_posted_journal_core_fields_are_immutable(self, uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
        result = post(
            [
                (ledger.settlement.id, Direction.DEBIT, "10.00"),
                (ledger.customer_a.id, Direction.CREDIT, "10.00"),
            ]
        )
        jid = result.journal.id
        with uow_factory() as uow, pytest.raises(DBAPIError, match="IMMUTABLE_POSTING"):
            uow.session.execute(
                text("UPDATE journal_entries SET reference = 'X' WHERE id = :id"), {"id": jid}
            )
        with uow_factory() as uow, pytest.raises(DBAPIError, match="IMMUTABLE_POSTING"):
            uow.session.execute(text("DELETE FROM journal_entries WHERE id = :id"), {"id": jid})
        with uow_factory() as uow, pytest.raises(DBAPIError, match="IMMUTABLE_POSTING"):
            uow.session.execute(
                text("UPDATE journal_entries SET status = 'PENDING' WHERE id = :id"), {"id": jid}
            )

    def test_unbalanced_rows_cannot_be_committed(self, uow_factory, ledger) -> None:  # type: ignore[no-untyped-def]
        jid = uuid.uuid4()
        with uow_factory() as uow:
            uow.session.execute(
                text(
                    "INSERT INTO journal_entries (id, reference, description, booking_date, "
                    "value_date, status, currency, posted_at) "
                    "VALUES (:id, 'RAW', '', '2026-10-13', '2026-10-13', 'POSTED', 'GBP', now())"
                ),
                {"id": jid},
            )
            uow.session.execute(
                text(
                    "INSERT INTO postings (id, journal_entry_id, account_id, direction, amount, "
                    "currency) VALUES (:p1, :jid, :a1, 'DEBIT', 100, 'GBP'), "
                    "(:p2, :jid, :a2, 'CREDIT', 99.99, 'GBP')"
                ),
                {
                    "p1": uuid.uuid4(),
                    "p2": uuid.uuid4(),
                    "jid": jid,
                    "a1": ledger.settlement.id,
                    "a2": ledger.customer_a.id,
                },
            )
            with pytest.raises(DBAPIError, match="UNBALANCED_JOURNAL"):
                uow.commit()
        assert table_counts(uow_factory)["journals"] == 0

    def test_negative_amount_rejected_by_check_constraint(self, uow_factory, ledger) -> None:  # type: ignore[no-untyped-def]
        with uow_factory() as uow:
            jid = uuid.uuid4()
            uow.session.execute(
                text(
                    "INSERT INTO journal_entries (id, reference, description, booking_date, "
                    "value_date, status, currency) "
                    "VALUES (:id, 'RAW', '', '2026-10-13', '2026-10-13', 'PENDING', 'GBP')"
                ),
                {"id": jid},
            )
            with pytest.raises(IntegrityError, match="ck_postings_amount_positive"):
                uow.session.execute(
                    text(
                        "INSERT INTO postings (id, journal_entry_id, account_id, direction, "
                        "amount, currency) VALUES (:p, :jid, :a, 'DEBIT', -1, 'GBP')"
                    ),
                    {"p": uuid.uuid4(), "jid": jid, "a": ledger.settlement.id},
                )


def test_lock_accounts_reports_missing(uow_factory, ledger) -> None:  # type: ignore[no-untyped-def]
    from corebank.domain.exceptions import AccountNotFoundError

    with uow_factory() as uow, pytest.raises(AccountNotFoundError):
        posting_service.lock_accounts(uow, {ledger.settlement.id, uuid.uuid4()})
