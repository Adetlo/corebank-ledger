from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str = Field(examples=["corebank-ledger"])
    version: str = Field(examples=["0.1.0"])
    checks: dict[str, str] = Field(default_factory=dict, examples=[{"database": "ok"}])
