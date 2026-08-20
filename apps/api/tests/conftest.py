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
    "DATABASE_URL", "postgresql+asyncpg://app_user:app_user_local_dev@localhost:5452/ttli"
)
os.environ.setdefault(
    "DATABASE_URL_SYNC", "postgresql+psycopg2://ttli:ttli_local_dev@localhost:5452/ttli"
)
os.environ.setdefault("APP_DB_PASSWORD", "app_user_local_dev")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters-long")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", base64.b64encode(b"F" * 32).decode())
os.environ.setdefault("BLIND_INDEX_KEY", base64.b64encode(b"B" * 32).decode())

# Tests never touch the database or Redis index the dev servers use.
# For the project's whole life they shared `ttli` and redis db 0 with
# the running app, and the leakage was not hypothetical: 1,320 test
# courses in the catalogue, 16 stale workshop sessions breaking a real
# test, and every `client` fixture's flushdb() nuking the dev server's
# tenant cache mid-session. The rewrite below is unconditional — however
# DATABASE_URL arrives (shell, .env, CI), tests run against
# `<dbname>_test` on the same server and redis db 1, and provision the
# test database themselves on first use (`_ensure_test_database`).
TEST_DB_SUFFIX = "_test"


def _swap_db_name(url: str, name: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


def _test_db_name(url: str) -> str:
    plain = url.rpartition("/")[2]
    return plain if plain.endswith(TEST_DB_SUFFIX) else plain + TEST_DB_SUFFIX


_TEST_DB = _test_db_name(os.environ["DATABASE_URL"])
os.environ["DATABASE_URL"] = _swap_db_name(os.environ["DATABASE_URL"], _TEST_DB)
os.environ["DATABASE_URL_SYNC"] = _swap_db_name(os.environ["DATABASE_URL_SYNC"], _TEST_DB)
_redis = os.environ.get("REDIS_URL", "redis://localhost:6399/0")
os.environ["REDIS_URL"] = (
    _redis.rsplit("/", 1)[0] + "/1" if _redis.count("/") >= 3 else _redis + "/1"
)

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


_test_db_provisioned = False


def _ensure_test_database(settings: Settings) -> None:
    """Create + migrate the isolated test database, once per session.

    The maintenance connection is the sync (owner) URL pointed at the
    `postgres` database; extensions mirror infra/postgres-init/
    01-extensions.sql (an init-dir script only runs on a volume's FIRST
    boot, so the test database can never rely on it); the schema comes
    from the real migrations — which also proves, every session, that
    `alembic upgrade head` works on an empty database. Migration 0001's
    role creation is idempotent, so the cluster-wide `app_user` existing
    already (the dev database created it) is fine.
    """
    global _test_db_provisioned
    if _test_db_provisioned:
        return
    import sqlalchemy as sa
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    admin = sa.create_engine(
        _swap_db_name(settings.database_url_sync, "postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        exists = conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _TEST_DB}
        ).scalar()
        if not exists:
            conn.execute(sa.text(f'CREATE DATABASE "{_TEST_DB}"'))
    admin.dispose()

    owner = sa.create_engine(settings.database_url_sync, isolation_level="AUTOCOMMIT")
    with owner.connect() as conn:
        for ext in ("citext", "pg_trgm", "pgcrypto"):
            conn.execute(sa.text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
    owner.dispose()

    alembic_command.upgrade(AlembicConfig("alembic.ini"), "head")
    _test_db_provisioned = True


@pytest.fixture
def database_url(settings: Settings) -> str:
    if not _database_reachable(settings.database_url):
        pytest.skip(
            "no Postgres on the configured DATABASE_URL — "
            "run: docker compose -f infra/docker-compose.yml up -d postgres"
        )
    _ensure_test_database(settings)
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
