"""Test fixtures.

Unit tests run anywhere. Integration tests need a live Postgres with the
migrations applied, and are marked `integration` so CI can assert that they
actually ran rather than quietly skipping.
"""

from __future__ import annotations

import base64
import os
import socket
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://ttli:ttli_local_dev@localhost:5452/ttli"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", base64.b64encode(b"F" * 32).decode())
os.environ.setdefault("BLIND_INDEX_KEY", base64.b64encode(b"B" * 32).decode())

from src.core.config import Settings, get_settings
from src.core.crypto import CryptoBox
from src.core.db import (
    dispose_engine,
    get_sessionmaker,
    init_engine,
    set_tenant,
)


def _database_reachable(url: str) -> bool:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    host, port = parsed.hostname or "localhost", parsed.port or 5432
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def crypto(settings: Settings) -> CryptoBox:
    return CryptoBox(settings.encryption_key_bytes(), settings.blind_index_key_bytes())


@pytest.fixture
def database_url(settings: Settings) -> str:
    if not _database_reachable(settings.database_url):
        pytest.skip(
            "no Postgres on the configured DATABASE_URL — "
            "run: docker compose -f infra/docker-compose.yml up -d postgres"
        )
    return settings.database_url


@pytest.fixture
async def session(settings: Settings, database_url: str) -> AsyncIterator[AsyncSession]:
    """A session with no tenant bound. RLS therefore hides every scoped row."""
    init_engine(settings)
    factory = get_sessionmaker()
    async with factory() as s, s.begin():
        yield s
        await s.rollback()
    await dispose_engine()


@pytest.fixture
async def tenant_session_factory(settings: Settings, database_url: str):  # type: ignore[no-untyped-def]
    """Yields a callable giving a session bound to a chosen tenant."""
    init_engine(settings)
    factory = get_sessionmaker()

    class _Maker:
        def __call__(self, tenant_id: uuid.UUID | None):
            class _Ctx:
                async def __aenter__(self) -> AsyncSession:
                    self._s = factory()
                    await self._s.__aenter__()
                    self._t = self._s.begin()
                    await self._t.__aenter__()
                    await set_tenant(self._s, tenant_id)
                    return self._s

                async def __aexit__(self, *exc: object) -> None:
                    await self._t.__aexit__(*exc)  # type: ignore[arg-type]
                    await self._s.__aexit__(*exc)  # type: ignore[arg-type]

            return _Ctx()

    yield _Maker()
    await dispose_engine()
