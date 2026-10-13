"""Shared fixtures.

All integration/API tests run against a **real PostgreSQL** so that row locks,
deferred constraint triggers and JSONB behave exactly as in production.

* If ``TEST_DATABASE_URL`` is set (CI uses a service container) it is used.
* Otherwise an embedded PostgreSQL is started via the ``pgserver`` wheel.

The schema is created by running the Alembic migrations, so the migrations
themselves are exercised on every test run. Tables are truncated between
tests, which is far cheaper than recreating the schema.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from corebank.api.app import create_app
from corebank.application.unit_of_work import UnitOfWork
from corebank.config import Settings
from corebank.domain.events import DomainEvent, EventDispatcher
from corebank.infrastructure.database import create_session_factory

ROOT = Path(__file__).resolve().parent.parent
TABLES = ("audit_events", "idempotency_records", "postings", "journal_entries", "accounts")


def _database_url(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Any]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url, None
    pgserver = pytest.importorskip(
        "pgserver", reason="pgserver not installed and no TEST_DATABASE_URL"
    )
    datadir = tmp_path_factory.mktemp("pgdata")
    server = pgserver.get_server(str(datadir))
    uri = server.get_uri()  # postgresql://postgres:@/postgres?host=/path/to/socket
    return uri.replace("postgresql://", "postgresql+psycopg://", 1), server


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    url, server = _database_url(tmp_path_factory)
    try:
        yield url
    finally:
        if server is not None:
            server.cleanup()
            # pgserver logs again from an atexit hook after pytest closed its streams.
            logging.getLogger("pgserver").disabled = True


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,  # type: ignore[arg-type]
        app_env="test",
        log_level="WARNING",
        log_format="console",
        database_pool_size=5,
        database_max_overflow=5,
    )


@pytest.fixture(scope="session")
def engine(settings: Settings, database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    os.environ["DATABASE_URL"] = database_url
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Engine]:
    """A migrated database engine; tables are truncated after each test."""
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {', '.join(TABLES)} CASCADE"))


class RecordingDispatcher(EventDispatcher):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[DomainEvent] = []
        self.subscribe(self.events.append)


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def uow_factory(db: Engine, dispatcher: RecordingDispatcher):  # type: ignore[no-untyped-def]
    factory = create_session_factory(db)

    def make() -> UnitOfWork:
        return UnitOfWork(factory, dispatcher)

    return make


@pytest.fixture
def app(settings: Settings, db: Engine, dispatcher: RecordingDispatcher):  # type: ignore[no-untyped-def]
    return create_app(settings, engine=db, dispatcher=dispatcher)


@pytest.fixture
def client(app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with TestClient(app) as client:
        yield client
