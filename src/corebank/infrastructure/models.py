"""ORM models mirroring the PostgreSQL schema.

Database constraints reinforce domain rules wherever feasible:

* ``postings.amount > 0`` and ``direction IN ('DEBIT','CREDIT')``.
* Currency, status and type columns are constrained to their enumerations.
* ``journal_entries.reversal_of`` / ``reversed_by`` are UNIQUE so an entry can
  be reversed at most once and a reversal reverses exactly one entry.
* Idempotency records are UNIQUE on ``(scope, idempotency_key)``.
* Triggers (defined in the Alembic migration, not here) make postings and
  posted journal entries immutable and verify debits == credits at commit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from corebank.domain.money import CURRENCIES

CURRENCY_CODES = tuple(CURRENCIES)
_currency_sql = ", ".join(f"'{c}'" for c in CURRENCY_CODES)


class Base(DeclarativeBase):
    pass


class AccountModel(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)
    allow_negative_balance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    postings: Mapped[list[PostingModel]] = relationship(back_populates="account")

    __table_args__ = (
        CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE')",
            name="ck_accounts_type",
        ),
        CheckConstraint("normal_balance IN ('DEBIT','CREDIT')", name="ck_accounts_normal_balance"),
        CheckConstraint("status IN ('ACTIVE','FROZEN','CLOSED')", name="ck_accounts_status"),
        CheckConstraint(f"currency IN ({_currency_sql})", name="ck_accounts_currency"),
        CheckConstraint("version >= 1", name="ck_accounts_version"),
        Index("ix_accounts_type_currency", "account_type", "currency"),
        Index("ix_accounts_status", "status"),
    )


class JournalEntryModel(Base):
    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", name="fk_journal_entries_reversal_of"),
        nullable=True,
        unique=True,
    )
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", name="fk_journal_entries_reversed_by"),
        nullable=True,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    postings: Mapped[list[PostingModel]] = relationship(
        back_populates="journal_entry", cascade="all", order_by="PostingModel.created_at"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','POSTED','REVERSED','FAILED')", name="ck_journal_entries_status"
        ),
        CheckConstraint(f"currency IN ({_currency_sql})", name="ck_journal_entries_currency"),
        CheckConstraint(
            "(status <> 'POSTED' AND status <> 'REVERSED') OR posted_at IS NOT NULL",
            name="ck_journal_entries_posted_at",
        ),
        CheckConstraint("reversal_of IS NULL OR reversal_of <> id", name="ck_journal_entries_self"),
        Index("ix_journal_entries_reference", "reference"),
        Index("ix_journal_entries_booking_date", "booking_date"),
        Index("ix_journal_entries_status", "status"),
        Index("ix_journal_entries_idempotency_key", "idempotency_key"),
        Index("ix_journal_entries_created_at", "created_at"),
    )


class PostingModel(Base):
    __tablename__ = "postings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journal_entries.id", name="fk_postings_journal_entry"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", name="fk_postings_account"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    journal_entry: Mapped[JournalEntryModel] = relationship(back_populates="postings")
    account: Mapped[AccountModel] = relationship(back_populates="postings")

    __table_args__ = (
        CheckConstraint("direction IN ('DEBIT','CREDIT')", name="ck_postings_direction"),
        CheckConstraint("amount > 0", name="ck_postings_amount_positive"),
        CheckConstraint(f"currency IN ({_currency_sql})", name="ck_postings_currency"),
        Index("ix_postings_journal_entry_id", "journal_entry_id"),
        Index("ix_postings_account_id", "account_id"),
        Index("ix_postings_account_journal", "account_id", "journal_entry_id"),
    )


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
        Index("ix_idempotency_created_at", "created_at"),
    )


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_correlation_id", "correlation_id"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )
