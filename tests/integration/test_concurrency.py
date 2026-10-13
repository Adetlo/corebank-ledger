"""Concurrency: row locks make concurrent spends against one account serialise safely."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from corebank.application.account_service import AccountService
from corebank.application.transfer_service import TransferService
from corebank.domain.exceptions import InsufficientFundsError
from corebank.domain.money import Money
from corebank.domain.transactions import TransferCommand
from tests.integration.conftest import TODAY


def test_concurrent_transfers_never_overdraw(uow_factory, ctx, ledger, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "500.00")
    workers = 12
    barrier = threading.Barrier(workers)

    def attempt(i: int) -> bool:
        barrier.wait()
        command = TransferCommand(
            ledger.customer_a.id,
            ledger.customer_b.id,
            Money.of("100.00", "GBP"),
            f"RACE-{i}",
            TODAY,
        )
        try:
            TransferService(uow_factory()).transfer(command, ctx, idempotency_key=f"race-{i}")
            return True
        except InsufficientFundsError:
            return False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(attempt, range(workers)))

    assert outcomes.count(True) == 5
    accounts = AccountService(uow_factory())
    assert accounts.get_balance(ledger.customer_a.id).balance.amount == Decimal("0.00")
    assert accounts.get_balance(ledger.customer_b.id).balance.amount == Decimal("500.00")


def test_opposite_direction_transfers_do_not_deadlock(uow_factory, ctx, ledger, fund) -> None:  # type: ignore[no-untyped-def]
    fund(ledger.customer_a, "100.00")
    fund(ledger.customer_b, "100.00")
    workers = 10
    barrier = threading.Barrier(workers)

    def attempt(i: int) -> None:
        barrier.wait()
        src, dst = (
            (ledger.customer_a, ledger.customer_b)
            if i % 2
            else (ledger.customer_b, ledger.customer_a)
        )
        TransferService(uow_factory()).transfer(
            TransferCommand(src.id, dst.id, Money.of("10.00", "GBP"), f"PP-{i}", TODAY),
            ctx,
            idempotency_key=f"pp-{i}",
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(attempt, range(workers)))

    accounts = AccountService(uow_factory())
    assert accounts.get_balance(ledger.customer_a.id).balance.amount == Decimal("100.00")
    assert accounts.get_balance(ledger.customer_b.id).balance.amount == Decimal("100.00")
