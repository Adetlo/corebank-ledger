from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from corebank.application.context import RequestContext
from corebank.domain.accounts import Account, AccountBalance, AccountStatus, AccountType
from corebank.domain.events import AccountCreated
from corebank.domain.exceptions import AccountNotFoundError
from corebank.domain.money import Money, validate_currency
from corebank.infrastructure.repositories.audit import AuditEvent, AuditEventType

if TYPE_CHECKING:
    from corebank.application.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class CreateAccountCommand:
    account_name: str
    account_type: AccountType
    currency: str
    allow_negative_balance: bool | None = None


class AccountService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create_account(self, command: CreateAccountCommand, ctx: RequestContext) -> Account:
        account = Account(
            account_name=command.account_name,
            account_type=AccountType(command.account_type),
            currency=validate_currency(command.currency),
            allow_negative_balance=command.allow_negative_balance,
        )
        with self._uow as uow:
            saved = uow.accounts.add(account)
            uow.audit.add(
                AuditEvent(
                    entity_type="account",
                    entity_id=saved.id,
                    event_type=AuditEventType.ACCOUNT_CREATED,
                    correlation_id=ctx.correlation_id,
                    actor=ctx.actor,
                    metadata={
                        "account_number": saved.account_number,
                        "account_type": saved.account_type.value,
                        "currency": saved.currency,
                    },
                )
            )
            uow.add_event(
                AccountCreated(
                    correlation_id=ctx.correlation_id,
                    account_id=saved.id,
                    account_type=saved.account_type.value,
                    currency=saved.currency,
                )
            )
            uow.commit()
        return saved

    def get_account(self, account_id: UUID) -> Account:
        with self._uow as uow:
            account = uow.accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(account_id=str(account_id))
        return account

    def list_accounts(
        self,
        *,
        limit: int,
        offset: int,
        account_type: AccountType | None = None,
        currency: str | None = None,
        status: AccountStatus | None = None,
    ) -> tuple[list[Account], int]:
        with self._uow as uow:
            return uow.accounts.list(
                limit=limit,
                offset=offset,
                account_type=account_type.value if account_type else None,
                currency=validate_currency(currency) if currency else None,
                status=status.value if status else None,
            )

    def get_balance(self, account_id: UUID, *, as_of_date: date | None = None) -> AccountBalance:
        with self._uow as uow:
            account = uow.accounts.get(account_id)
            if account is None:
                raise AccountNotFoundError(account_id=str(account_id))
            return balance_for(uow, account, as_of_date=as_of_date)

    def change_status(
        self, account_id: UUID, new_status: AccountStatus, ctx: RequestContext
    ) -> Account:
        with self._uow as uow:
            account = uow.accounts.get(account_id, for_update=True)
            if account is None:
                raise AccountNotFoundError(account_id=str(account_id))
            current = balance_for(uow, account)
            updated = account.transition_to(new_status, current_balance=current.balance)
            uow.accounts.save(updated, expected_version=account.version)
            uow.audit.add(
                AuditEvent(
                    entity_type="account",
                    entity_id=account.id,
                    event_type=AuditEventType.ACCOUNT_STATUS_CHANGED,
                    correlation_id=ctx.correlation_id,
                    actor=ctx.actor,
                    metadata={"from": account.status.value, "to": updated.status.value},
                )
            )
            uow.commit()
        return updated


def balance_for(
    uow: UnitOfWork, account: Account, *, as_of_date: date | None = None
) -> AccountBalance:
    """Derive an account balance from its effective postings."""
    totals = uow.accounts.balance_totals(account.id, as_of_date=as_of_date)
    return AccountBalance.derive(
        account,
        Money(Decimal(totals.debit_total), account.currency),
        Money(Decimal(totals.credit_total), account.currency),
        as_of_date=as_of_date,
        posting_count=totals.posting_count,
    )
