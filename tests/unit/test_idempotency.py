from __future__ import annotations

from typing import Any

import pytest

from corebank.application.idempotency import IdempotencyGuard, canonical_hash
from corebank.domain.exceptions import IdempotencyConflictError
from corebank.infrastructure.repositories.idempotency import IdempotencyRecord


class FakeRepo:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], IdempotencyRecord] = {}

    def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        return self.records.get((scope, key))

    def add(self, record: IdempotencyRecord) -> None:
        self.records[(record.scope, record.idempotency_key)] = record


def test_canonical_hash_is_order_independent() -> None:
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_guard_remembers_and_replays() -> None:
    repo = FakeRepo()
    guard = IdempotencyGuard("scope", "key-1", {"amount": "1.00"})
    assert guard.enabled
    assert guard.lookup(repo) is None
    guard.remember(repo, resource_id=None, response_status=201, response_body={"x": 1})
    replay = guard.lookup(repo)
    assert replay is not None and replay.response_status == 201 and replay.response_body == {"x": 1}


def test_guard_conflict_on_different_payload() -> None:
    repo = FakeRepo()
    IdempotencyGuard("scope", "key-1", {"amount": "1.00"}).remember(
        repo, resource_id=None, response_status=201, response_body={}
    )
    with pytest.raises(IdempotencyConflictError):
        IdempotencyGuard("scope", "key-1", {"amount": "2.00"}).lookup(repo)


def test_scopes_are_independent() -> None:
    repo = FakeRepo()
    IdempotencyGuard("a", "key", {"p": 1}).remember(
        repo, resource_id=None, response_status=201, response_body={}
    )
    assert IdempotencyGuard("b", "key", {"p": 2}).lookup(repo) is None


def test_disabled_guard_is_a_noop() -> None:
    repo = FakeRepo()
    guard = IdempotencyGuard("a", None, {})
    assert not guard.enabled
    assert guard.lookup(repo) is None
    guard.remember(repo, resource_id=None, response_status=201, response_body={})
    assert repo.records == {}


@pytest.mark.parametrize("bad", ["", "   ", "x" * 129])
def test_key_validation(bad: Any) -> None:
    with pytest.raises(IdempotencyConflictError):
        IdempotencyGuard("a", bad, {})
