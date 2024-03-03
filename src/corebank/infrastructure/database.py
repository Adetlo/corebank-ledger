"""SQLAlchemy engine and session management.

Only PostgreSQL is supported. The service relies on PostgreSQL-specific
behaviour (``SELECT ... FOR UPDATE``, deferred constraint triggers, JSONB),
so supporting SQLite would silently weaken the guarantees this project exists
to demonstrate (see ADR 0005).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from corebank.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    url = make_url(settings.database_dsn)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("corebank-ledger requires a postgresql+psycopg DATABASE_URL")
    return create_engine(
        url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        echo=settings.database_echo,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False lets us build responses from committed objects.
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


def check_database(engine: Engine) -> bool:
    """Readiness probe: can we open a connection and run a trivial query?"""
    with engine.connect() as conn:
        value = conn.execute(text("SELECT 1")).scalar_one()
        return bool(value == 1)
