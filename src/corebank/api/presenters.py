"""Domain -> response schema conversion."""

from __future__ import annotations

from corebank.application.reconciliation_service import LedgerCheck, TrialBalance
from corebank.domain.accounts import Account, AccountBalance
from corebank.domain.ledger import JournalEntry, summarise
from corebank.infrastructure.repositories.audit import AuditEvent
from corebank.schemas.accounts import AccountResponse, BalanceResponse
from corebank.schemas.journal import AuditEventResponse, JournalEntryResponse, PostingResponse
from corebank.schemas.reconciliation import (
    LedgerCheckLineResponse,
    LedgerCheckResponse,
    TrialBalanceLineResponse,
    TrialBalanceResponse,
)
from corebank.schemas.transfers import TransferResponse


def account_response(account: Account) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        account_number=account.account_number,
        account_name=account.account_name,
        account_type=account.account_type,
        currency=account.currency,
        status=account.status,
        normal_balance=account.normal_balance,
        allow_negative_balance=bool(account.allow_negative_balance),
        version=account.version,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def balance_response(balance: AccountBalance) -> BalanceResponse:
    return BalanceResponse(
        account_id=balance.account_id,
        currency=balance.currency,
        normal_balance=balance.normal_balance,
        debit_total=balance.debit_total.amount,
        credit_total=balance.credit_total.amount,
        balance=balance.balance.amount,
        as_of_date=balance.as_of_date,
        posting_count=balance.posting_count,
    )


def journal_response(entry: JournalEntry) -> JournalEntryResponse:
    check = summarise(entry.postings)
    return JournalEntryResponse(
        id=entry.id,
        reference=entry.reference,
        description=entry.description,
        booking_date=entry.booking_date,
        value_date=entry.value_date,
        status=entry.status,
        currency=entry.currency,
        total_debits=check.total_debits.amount,
        total_credits=check.total_credits.amount,
        postings=[
            PostingResponse(
                id=p.id,
                journal_entry_id=p.journal_entry_id,
                account_id=p.account_id,
                direction=p.direction,
                amount=p.money.amount,
                currency=p.money.currency,
                created_at=p.created_at,
            )
            for p in entry.postings
        ],
        idempotency_key=entry.idempotency_key,
        metadata=entry.metadata,
        reversal_of=entry.reversal_of,
        reversed_by=entry.reversed_by,
        created_at=entry.created_at,
        posted_at=entry.posted_at,
    )


def transfer_response(entry: JournalEntry) -> TransferResponse:
    from uuid import UUID

    check = summarise(entry.postings)
    return TransferResponse(
        transfer_id=entry.id,
        reference=entry.reference,
        status=entry.status,
        source_account_id=UUID(str(entry.metadata["source_account_id"])),
        destination_account_id=UUID(str(entry.metadata["destination_account_id"])),
        amount=check.total_debits.amount,
        currency=check.currency,
        booking_date=entry.booking_date,
        value_date=entry.value_date,
        journal_entry=journal_response(entry),
    )


def trial_balance_response(tb: TrialBalance) -> TrialBalanceResponse:
    return TrialBalanceResponse(
        currency=tb.currency,
        as_of_date=tb.as_of_date,
        accounts=[
            TrialBalanceLineResponse(
                account_id=line.account_id,
                account_number=line.account_number,
                account_name=line.account_name,
                account_type=line.account_type,
                normal_balance=line.normal_balance,
                currency=line.currency,
                debit_total=line.debit_total.amount,
                credit_total=line.credit_total.amount,
                net_balance=line.net_balance.amount,
            )
            for line in tb.lines
        ],
        total_debits=tb.total_debits.amount,
        total_credits=tb.total_credits.amount,
        difference=tb.difference.amount,
        balanced=tb.balanced,
    )


def ledger_check_response(check: LedgerCheck) -> LedgerCheckResponse:
    return LedgerCheckResponse(
        as_of_date=check.as_of_date,
        balanced=check.balanced,
        currencies=[
            LedgerCheckLineResponse(
                currency=c.currency,
                total_debits=c.total_debits.amount,
                total_credits=c.total_credits.amount,
                difference=c.difference.amount,
                balanced=c.balanced,
                posting_count=c.posting_count,
            )
            for c in check.currencies
        ],
        unbalanced_journal_ids=check.unbalanced_journal_ids,
    )


def audit_event_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        event_type=event.event_type.value,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        actor=event.actor,
        metadata=event.metadata,
    )
