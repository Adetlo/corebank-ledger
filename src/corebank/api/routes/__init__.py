from fastapi import APIRouter

from corebank.api.routes import (
    accounts,
    health,
    journal_entries,
    payments,
    reconciliation,
    transfers,
)

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(accounts.router)
api_v1.include_router(journal_entries.router)
api_v1.include_router(transfers.router)
api_v1.include_router(reconciliation.router)
api_v1.include_router(payments.router)

__all__ = ["api_v1", "health"]
