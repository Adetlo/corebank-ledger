"""Per-request execution context shared by all use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


def new_correlation_id() -> str:
    return uuid4().hex


@dataclass(frozen=True, slots=True)
class RequestContext:
    correlation_id: str = field(default_factory=new_correlation_id)
    actor: str | None = None
    source: str = "api"
