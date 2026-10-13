"""Environment-based configuration (12-factor style).

Values are read from the process environment or a local ``.env`` file. The
``.env`` file is git-ignored; ``.env.example`` documents every variable.
Secrets are never logged: :meth:`Settings.safe_summary` masks the DSN.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "CoreBank Ledger"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    database_url: SecretStr = Field(
        default=SecretStr("postgresql+psycopg://corebank:corebank@localhost:5432/corebank"),
        description="SQLAlchemy DSN. Only the postgresql+psycopg dialect is supported.",
    )
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_echo: bool = False

    #: Hard cap on request body size for mutation endpoints (bytes).
    max_request_bytes: int = 256 * 1024
    #: Default and maximum page sizes for list endpoints.
    default_page_size: int = 50
    max_page_size: int = 200
    #: Whether financial mutation endpoints require an Idempotency-Key header.
    require_idempotency_key: bool = True
    #: Retention hint for idempotency records (not enforced by v1, documented).
    idempotency_ttl_hours: int = 24

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @property
    def database_dsn(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def safe_summary(self) -> dict[str, str | int | bool]:
        """Configuration view that is safe to log (credentials masked)."""
        url = make_url(self.database_dsn)
        return {
            "app_env": self.app_env,
            "log_level": self.log_level,
            "database": f"{url.drivername}://{url.host or 'local'}/{url.database or ''}",
            "max_request_bytes": self.max_request_bytes,
            "require_idempotency_key": self.require_idempotency_key,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
