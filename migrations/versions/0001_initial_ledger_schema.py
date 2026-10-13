"""Initial ledger schema: accounts, journal entries, postings, idempotency, audit.

Revision ID: 0001
Revises:
Create Date: 2026-10-13

Besides the tables, this migration installs three PostgreSQL triggers that
reinforce the domain invariants at the storage layer:

* ``postings`` rows can never be updated or deleted (immutability).
* ``journal_entries`` rows in POSTED/REVERSED status can only change
  ``status -> REVERSED`` and ``reversed_by`` (one-way, once).
* A DEFERRABLE INITIALLY DEFERRED constraint trigger verifies, at commit,
  that every effective journal entry has SUM(debits) == SUM(credits).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

CURRENCIES = "'GBP','USD','EUR','JPY','CHF','SGD','AUD'"


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_number", sa.String(32), nullable=False),
        sa.Column("account_name", sa.String(200), nullable=False),
        sa.Column("account_type", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("normal_balance", sa.String(6), nullable=False),
        sa.Column(
            "allow_negative_balance", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE')",
            name="ck_accounts_type",
        ),
        sa.CheckConstraint(
            "normal_balance IN ('DEBIT','CREDIT')", name="ck_accounts_normal_balance"
        ),
        sa.CheckConstraint("status IN ('ACTIVE','FROZEN','CLOSED')", name="ck_accounts_status"),
        sa.CheckConstraint(f"currency IN ({CURRENCIES})", name="ck_accounts_currency"),
        sa.CheckConstraint("version >= 1", name="ck_accounts_version"),
        sa.UniqueConstraint("account_number", name="uq_accounts_account_number"),
    )
    op.create_index("ix_accounts_type_currency", "accounts", ["account_type", "currency"])
    op.create_index("ix_accounts_status", "accounts", ["status"])

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reversal_of", sa.Uuid(), nullable=True),
        sa.Column("reversed_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','POSTED','REVERSED','FAILED')", name="ck_journal_entries_status"
        ),
        sa.CheckConstraint(f"currency IN ({CURRENCIES})", name="ck_journal_entries_currency"),
        sa.CheckConstraint(
            "(status <> 'POSTED' AND status <> 'REVERSED') OR posted_at IS NOT NULL",
            name="ck_journal_entries_posted_at",
        ),
        sa.CheckConstraint(
            "reversal_of IS NULL OR reversal_of <> id", name="ck_journal_entries_self"
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of"], ["journal_entries.id"], name="fk_journal_entries_reversal_of"
        ),
        sa.ForeignKeyConstraint(
            ["reversed_by"], ["journal_entries.id"], name="fk_journal_entries_reversed_by"
        ),
        sa.UniqueConstraint("reversal_of", name="uq_journal_entries_reversal_of"),
        sa.UniqueConstraint("reversed_by", name="uq_journal_entries_reversed_by"),
    )
    op.create_index("ix_journal_entries_reference", "journal_entries", ["reference"])
    op.create_index("ix_journal_entries_booking_date", "journal_entries", ["booking_date"])
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"])
    op.create_index("ix_journal_entries_idempotency_key", "journal_entries", ["idempotency_key"])
    op.create_index("ix_journal_entries_created_at", "journal_entries", ["created_at"])

    op.create_table(
        "postings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("journal_entry_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("direction IN ('DEBIT','CREDIT')", name="ck_postings_direction"),
        sa.CheckConstraint("amount > 0", name="ck_postings_amount_positive"),
        sa.CheckConstraint(f"currency IN ({CURRENCIES})", name="ck_postings_currency"),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], name="fk_postings_journal_entry"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_postings_account"),
    )
    op.create_index("ix_postings_journal_entry_id", "postings", ["journal_entry_id"])
    op.create_index("ix_postings_account_id", "postings", ["account_id"])
    op.create_index("ix_postings_account_journal", "postings", ["account_id", "journal_entry_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_created_at", "idempotency_records", ["created_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])

    # ------------------------------------------------------------------
    # Storage-level reinforcement of the ledger invariants.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corebank_postings_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'IMMUTABLE_POSTING: postings cannot be % (journal_entry_id=%)',
                lower(TG_OP), OLD.journal_entry_id
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_postings_immutable
        BEFORE UPDATE OR DELETE ON postings
        FOR EACH ROW EXECUTE FUNCTION corebank_postings_immutable();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corebank_journal_entries_immutable() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status IN ('POSTED', 'REVERSED') THEN
                    RAISE EXCEPTION 'IMMUTABLE_POSTING: posted journal entries cannot be deleted (id=%)', OLD.id
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status IN ('POSTED', 'REVERSED') THEN
                IF NEW.reference IS DISTINCT FROM OLD.reference
                   OR NEW.booking_date IS DISTINCT FROM OLD.booking_date
                   OR NEW.value_date IS DISTINCT FROM OLD.value_date
                   OR NEW.currency IS DISTINCT FROM OLD.currency
                   OR NEW.posted_at IS DISTINCT FROM OLD.posted_at
                   OR NEW.reversal_of IS DISTINCT FROM OLD.reversal_of
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                   OR NEW.description IS DISTINCT FROM OLD.description
                   OR NEW.metadata IS DISTINCT FROM OLD.metadata THEN
                    RAISE EXCEPTION 'IMMUTABLE_POSTING: posted journal entries are immutable (id=%)', OLD.id
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF OLD.status = 'REVERSED' AND (NEW.status <> 'REVERSED' OR NEW.reversed_by IS DISTINCT FROM OLD.reversed_by) THEN
                    RAISE EXCEPTION 'JOURNAL_ALREADY_REVERSED: reversal link is permanent (id=%)', OLD.id
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF OLD.status = 'POSTED' AND NOT (
                    (NEW.status = 'POSTED' AND NEW.reversed_by IS NULL)
                    OR (NEW.status = 'REVERSED' AND NEW.reversed_by IS NOT NULL)
                ) THEN
                    RAISE EXCEPTION 'IMMUTABLE_POSTING: POSTED may only move to REVERSED with reversed_by (id=%)', OLD.id
                        USING ERRCODE = 'restrict_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_journal_entries_immutable
        BEFORE UPDATE OR DELETE ON journal_entries
        FOR EACH ROW EXECUTE FUNCTION corebank_journal_entries_immutable();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corebank_journal_balanced() RETURNS trigger AS $$
        DECLARE
            v_journal_id uuid;
            v_status text;
            v_debits numeric(19, 4);
            v_credits numeric(19, 4);
            v_count integer;
        BEGIN
            IF TG_TABLE_NAME = 'postings' THEN
                v_journal_id := NEW.journal_entry_id;
            ELSE
                v_journal_id := NEW.id;
            END IF;
            SELECT status INTO v_status FROM journal_entries WHERE id = v_journal_id;
            IF v_status NOT IN ('POSTED', 'REVERSED') THEN
                RETURN NULL;
            END IF;
            SELECT COALESCE(SUM(CASE WHEN direction = 'DEBIT' THEN amount ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN direction = 'CREDIT' THEN amount ELSE 0 END), 0),
                   COUNT(*)
              INTO v_debits, v_credits, v_count
              FROM postings WHERE journal_entry_id = v_journal_id;
            IF v_count < 2 OR v_debits <> v_credits THEN
                RAISE EXCEPTION 'UNBALANCED_JOURNAL: journal % has debits % and credits %',
                    v_journal_id, v_debits, v_credits
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_postings_balanced
        AFTER INSERT ON postings
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION corebank_journal_balanced();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_journal_entries_balanced
        AFTER INSERT OR UPDATE OF status ON journal_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION corebank_journal_balanced();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_journal_entries_balanced ON journal_entries")
    op.execute("DROP TRIGGER IF EXISTS trg_postings_balanced ON postings")
    op.execute("DROP FUNCTION IF EXISTS corebank_journal_balanced()")
    op.execute("DROP TRIGGER IF EXISTS trg_journal_entries_immutable ON journal_entries")
    op.execute("DROP FUNCTION IF EXISTS corebank_journal_entries_immutable()")
    op.execute("DROP TRIGGER IF EXISTS trg_postings_immutable ON postings")
    op.execute("DROP FUNCTION IF EXISTS corebank_postings_immutable()")
    op.drop_table("audit_events")
    op.drop_table("idempotency_records")
    op.drop_table("postings")
    op.drop_table("journal_entries")
    op.drop_table("accounts")
