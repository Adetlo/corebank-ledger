"""Persistent idempotency for financial mutations.

Contract (see ``docs/LEDGER_INVARIANTS.md`` invariant 4):

* **same key + same payload**: the stored response is replayed; nothing is
  re-executed and no new postings are created.
* **same key + different payload**: ``IDEMPOTENCY_CONFLICT`` (HTTP 409).
* The idempotency record is written in the *same* transaction as the postings,
  so a crash between "post" and "remember" is impossible.
* A ``UNIQUE (scope, idempotency_key)`` constraint makes two racing requests
  with the same key safe: the loser's commit fails, it rolls back and replays
  the winner's stored response.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from corebank.domain.exceptions import IdempotencyConflictError
from corebank.infrastructure.repositories.idempotency import IdempotencyRecord

MAX_KEY_LENGTH = 128


def canonical_hash(payload: Any) -> str:
    """Stable SHA-256 over a canonical JSON rendering of the payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Replay:
    """A previously stored result returned instead of re-executing."""

    resource_id: UUID | None
    response_status: int
    response_body: dict[str, Any]


class IdempotencyGuard:
    """Helper bound to one scope + key + payload within a unit of work."""

    def __init__(self, scope: str, key: str | None, payload: Any) -> None:
        if key is not None and (not key.strip() or len(key) > MAX_KEY_LENGTH):
            raise IdempotencyConflictError(
                f"Idempotency-Key must be 1..{MAX_KEY_LENGTH} characters.", key_length=len(key)
            )
        self.scope = scope
        self.key = key.strip() if key else None
        self.request_hash = canonical_hash(payload)

    @property
    def enabled(self) -> bool:
        return self.key is not None

    def lookup(self, repository: Any) -> Replay | None:
        """Return a replay if this key was seen before; raise on payload mismatch."""
        if self.key is None:
            return None
        record: IdempotencyRecord | None = repository.get(self.scope, self.key)
        if record is None:
            return None
        if record.request_hash != self.request_hash:
            raise IdempotencyConflictError(scope=self.scope)
        return Replay(
            resource_id=record.resource_id,
            response_status=record.response_status,
            response_body=record.response_body,
        )

    def remember(
        self,
        repository: Any,
        *,
        resource_id: UUID | None,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        if self.key is None:
            return
        repository.add(
            IdempotencyRecord(
                scope=self.scope,
                idempotency_key=self.key,
                request_hash=self.request_hash,
                response_status=response_status,
                response_body=response_body,
                resource_id=resource_id,
            )
        )
