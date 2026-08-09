"""Application configuration.

`DATABASE_URL` deliberately has no default. An application that guesses its own
database will eventually guess a production one.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Core ---
    environment: Environment = "local"
    debug: bool = False
    api_port: int = 8010
    secret_key: str = ""

    # --- Database ---
    database_url: str
    database_url_sync: str = ""
    # Password for the non-superuser role the app connects as (DATABASE_URL).
    # Migrations create the role and grant it; they still run as the superuser
    # named in DATABASE_URL_SYNC, since DDL and role creation need that.
    app_db_password: str = ""

    # --- Redis ---
    redis_url: str = "redis://localhost:6399/0"

    # --- Auth ---
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    magic_link_minutes: int = 15
    mfa_pending_minutes: int = 5
    mfa_enroll_minutes: int = 10
    mfa_issuer_name: str = "TTLI"
    break_glass_admin_enabled: bool = False
    break_glass_admin_email: str = "admin@ttli.local"
    break_glass_admin_password: str = ""

    # --- Field encryption ---
    field_encryption_key: str = ""
    blind_index_key: str = ""

    # --- Object storage ---
    storage_backend: Literal["local", "s3", "azure"] = "local"
    storage_local_root: str = "var/storage"
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "af-south-1"
    azure_storage_connection_string: str = ""

    # --- Email ---
    smtp_host: str = "localhost"
    smtp_port: int = 1145
    email_from: str = "no-reply@ttli.local"

    # --- Observability ---
    sentry_dsn: str = ""
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// driver")
        return v

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations synchronously."""
        if self.database_url_sync:
            return self.database_url_sync
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def encryption_key_bytes(self) -> bytes:
        return base64.b64decode(self.field_encryption_key)

    def blind_index_key_bytes(self) -> bytes:
        return base64.b64decode(self.blind_index_key)


def check_production_safety(settings: Settings) -> list[str]:
    """Return every reason this configuration must not run in production.

    A list rather than a boolean, so the startup log names all the problems at
    once instead of revealing them one redeploy at a time.
    """
    problems: list[str] = []

    if not settings.is_production:
        return problems

    if settings.debug:
        problems.append("DEBUG is enabled")
    if settings.break_glass_admin_enabled:
        problems.append("BREAK_GLASS_ADMIN_ENABLED is on")
    if len(settings.secret_key) < 32:
        problems.append("SECRET_KEY is missing or shorter than 32 characters")
    if not settings.field_encryption_key:
        problems.append("FIELD_ENCRYPTION_KEY is not set")
    if not settings.blind_index_key:
        problems.append("BLIND_INDEX_KEY is not set")
    if not settings.app_db_password:
        problems.append("APP_DB_PASSWORD is not set")
    if settings.app_db_password in {"app_user_local_dev", "app_user_ci"}:
        problems.append("APP_DB_PASSWORD is a development credential")
    if settings.field_encryption_key == settings.blind_index_key:
        problems.append("FIELD_ENCRYPTION_KEY and BLIND_INDEX_KEY are the same value")
    if settings.storage_backend == "local":
        problems.append("STORAGE_BACKEND is 'local'")
    if settings.s3_access_key in {"ttli_dev", "minioadmin"}:
        problems.append("S3_ACCESS_KEY is a development credential")
    if not settings.sentry_dsn:
        problems.append("SENTRY_DSN is not set")
    if "localhost" in settings.database_url or "127.0.0.1" in settings.database_url:
        problems.append("DATABASE_URL points at localhost")
    if "sslmode=disable" in settings.database_url:
        problems.append("DATABASE_URL disables TLS")
    if "localhost" in settings.redis_url or "127.0.0.1" in settings.redis_url:
        # Tenant resolution and login rate limiting both depend on Redis now
        # (core/tenancy.py, services/rate_limit.py) — not just a cache.
        problems.append("REDIS_URL points at localhost")

    return problems


@lru_cache
def get_settings() -> Settings:
    # Values come from the environment and .env, so the required fields are not
    # passed positionally here.
    return Settings()


__all__ = ["Environment", "Field", "Settings", "check_production_safety", "get_settings"]
