"""Invariant 4: idempotent retries cannot duplicate economic events."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from corebank.application.posting_service import PostingService
from corebank.application.transfer_service import TransferService
from corebank.domain.exceptions import IdempotencyConflictError
from corebank.domain.ledger import Direction
from corebank.domain.money import Money
from corebank.domain.transactions import TransferCommand
from corebank.infrastructure.models import PostingModel
from corebank.infrastructure.repositories.audit import AuditEventType
from tests.integration.conftest import TODAY, journal_command


def posting_count(uow_factory) -> int:  # type: ignore[no-untyped-def]
    with uow_factory() as uow:
        return int(uow.session.execute(select(func.count(PostingModel.id))).scalar_one())


def test_replay_returns_original_without_new_postings(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    lines = [
        (ledger.settlement.id, Direction.DEBIT, "10.00"),
        (ledger.customer_a.id, Direction.CREDIT, "10.00"),
    ]
    first = post(lines, reference="R1", key="same-key")
    for _ in range(3):
        again = post(lines, reference="R1", key="same-key")
        assert again.replayed and again.journal.id == first.journal.id
    assert posting_count(uow_factory) == 2
    with uow_factory() as uow:
        events = uow.audit.list_for_entity(first.journal.id)
    assert [e.event_type for e in events].count(AuditEventType.IDEMPOTENT_REPLAY) == 3


def test_same_key_different_payload_conflicts(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    post(
        [
            (ledger.settlement.id, Direction.DEBIT, "10.00"),
            (ledger.customer_a.id, Direction.CREDIT, "10.00"),
        ],
        key="k1",
    )
    with pytest.raises(IdempotencyConflictError):
        post(
            [
                (ledger.settlement.id, Direction.DEBIT, "11.00"),
                (ledger.customer_a.id, Direction.CREDIT, "11.00"),
            ],
            key="k1",
        )
    assert posting_count(uow_factory) == 2


def test_keys_are_scoped_per_operation(uow_factory, ctx, ledger, post, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "100.00")
    post(
        [
            (ledger.customer_a.id, Direction.DEBIT, "1.00"),
            (ledger.fee_income.id, Direction.CREDIT, "1.00"),
        ],
        key="shared",
    )
    service = TransferService(uow_factory())
    result = service.transfer(
        TransferCommand(
            ledger.customer_a.id, ledger.customer_b.id, Money.of("1.00", "GBP"), "T", TODAY
        ),
        ctx,
        idempotency_key="shared",
    )
    assert not result.replayed
    assert posting_count(uow_factory) == 6


def test_failed_request_does_not_consume_key(uow_factory, ledger, post) -> None:  # type: ignore[no-untyped-def]
    from corebank.domain.exceptions import InsufficientFundsError

    lines = [
        (ledger.customer_a.id, Direction.DEBIT, "5.00"),
        (ledger.fee_income.id, Direction.CREDIT, "5.00"),
    ]
    with pytest.raises(InsufficientFundsError):
        post(lines, key="retry-me")
    post(
        [
            (ledger.settlement.id, Direction.DEBIT, "5.00"),
            (ledger.customer_a.id, Direction.CREDIT, "5.00"),
        ]
    )
    result = post(lines, key="retry-me")
    assert not result.replayed


def test_concurrent_requests_with_same_key_post_exactly_once(uow_factory, ctx, ledger) -> None:  # type: ignore[no-untyped-def]
    command = journal_command(
        [
            (ledger.settlement.id, Direction.DEBIT, "7.00"),
            (ledger.customer_a.id, Direction.CREDIT, "7.00"),
        ],
        reference="RACE",
    )
    workers = 8
    barrier = threading.Barrier(workers)

    def run() -> tuple[str, bool]:
        barrier.wait()
        result = PostingService(uow_factory()).post_journal(
            command, ctx, idempotency_key="race-key"
        )
        return str(result.journal.id), result.replayed

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: run(), range(workers)))

    ids = {r[0] for r in results}
    assert len(ids) == 1
    assert sum(1 for r in results if not r[1]) == 1
    assert posting_count(uow_factory) == 2
