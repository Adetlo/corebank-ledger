"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from corebank import __version__
from corebank.api.errors import register_exception_handlers
from corebank.api.middleware import CorrelationIdMiddleware, RequestSizeLimitMiddleware
from corebank.api.routes import api_v1, health
from corebank.application.unit_of_work import UnitOfWork
from corebank.config import Settings, get_settings
from corebank.domain.events import EventDispatcher, default_dispatcher
from corebank.infrastructure.database import create_db_engine, create_session_factory
from corebank.logging import configure_logging

logger = logging.getLogger("corebank")

DESCRIPTION = """
A production-style **educational** double-entry ledger service.

* Every journal entry must balance: `SUM(debits) == SUM(credits)`.
* Posted entries are immutable; corrections are reversals.
* Financial mutations require an `Idempotency-Key` header and are atomic.
* Balances are derived from postings, never stored as mutable truth.

This service uses synthetic data only. It is not affiliated with, derived from,
or representative of any production banking system. Authentication is
intentionally out of scope for v1 (see `SECURITY.md`).
"""

TAGS = [
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "accounts", "description": "Ledger accounts and derived balances."},
    {"name": "journal-entries", "description": "Balanced journal entries, search and reversals."},
    {"name": "transfers", "description": "Account-to-account transfers booked as journal entries."},
    {"name": "reconciliation", "description": "Trial balance and ledger integrity checks."},
    {"name": "payments", "description": "ISO 20022-inspired simplified payment instructions."},
]


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    dispatcher: EventDispatcher | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("starting", extra={"config": settings.safe_summary(), "version": __version__})
        yield
        app.state.engine.dispose()
        logger.info("stopped")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        contact={"name": "CoreBank Ledger (educational project)"},
        license_info={"name": "MIT"},
    )

    db_engine = engine or create_db_engine(settings)
    session_factory = create_session_factory(db_engine)
    event_dispatcher = dispatcher or default_dispatcher()

    app.state.settings = settings
    app.state.engine = db_engine
    app.state.uow_factory = lambda: UnitOfWork(session_factory, event_dispatcher)

    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_v1)
    return app
