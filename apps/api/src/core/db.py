"""Database engine, sessions, and the tenant context that row-level security reads.

Every request runs inside a transaction that begins with

    SET LOCAL app.tenant_id = '<uuid>'

and the RLS policies on tenant-scoped tables compare against it. Application
middleware alone is not enough: one forgotten `.where(tenant_id == ...)` in a
reporting query is a cross-tenant disclosure, and RLS turns that into a query
that simply returns nothing.

With no tenant set, `current_setting('app.tenant_id', true)` is NULL, the
comparison is NULL, and no rows match. Fails closed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import Settings

TENANT_GUC = "app.tenant_id"

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


@dataclass(frozen=True, slots=True)
class DatabasePoolStats:
    size: int
    checked_out: int
    overflow: int


@dataclass(frozen=True, slots=True)
class DatabaseRuntimeStats:
    connections: int
    max_connections: int
    size_bytes: int


def init_engine(settings: Settings) -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("init_engine() must be called before sessions are requested")
    return _sessionmaker


def database_pool_stats() -> DatabasePoolStats:
    """Return the app-side pool pressure without opening a connection."""

    if _engine is None:
        return DatabasePoolStats(size=0, checked_out=0, overflow=0)
    pool = _engine.sync_engine.pool
    return DatabasePoolStats(
        size=pool.size(),
        checked_out=pool.checkedout(),
        # QueuePool reports negative overflow before the base pool has filled;
        # operationally that still means zero overflow connections exist.
        overflow=max(0, pool.overflow()),
    )


async def database_runtime_stats() -> DatabaseRuntimeStats:
    """Sample PostgreSQL connection saturation and database size.

    This intentionally uses server-side facts rather than inferring database
    pressure from the application's own pool alone. `pg_stat_activity` exposes
    connection rows to ordinary users even though query text for other roles is
    protected, and `pg_database_size(current_database())` needs no elevated
    privilege.
    """

    factory = get_sessionmaker()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                        count(*)::int AS connections,
                        current_setting('max_connections')::int AS max_connections,
                        pg_database_size(current_database())::bigint AS size_bytes
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                    """
                )
            )
        ).one()
    return DatabaseRuntimeStats(
        connections=int(row.connections),
        max_connections=int(row.max_connections),
        size_bytes=int(row.size_bytes),
    )


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def set_tenant(session: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    """Bind the transaction to a tenant.

    `SET LOCAL` only survives inside a transaction, which is exactly what we
    want — the setting cannot leak to the next checkout of a pooled connection.
    The value is bound as a parameter rather than interpolated; set_config is
    the only way to parameterise a GUC.
    """
    if tenant_id is None:
        await session.execute(text("SELECT set_config(:k, '', true)"), {"k": TENANT_GUC})
    else:
        await session.execute(
            text("SELECT set_config(:k, :v, true)"),
            {"k": TENANT_GUC, "v": str(tenant_id)},
        )


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction, scoped to one tenant."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        await set_tenant(session, tenant_id)
        yield session


__all__ = [
    "DatabasePoolStats",
    "DatabaseRuntimeStats",
    "TENANT_GUC",
    "database_pool_stats",
    "database_runtime_stats",
    "dispose_engine",
    "get_sessionmaker",
    "init_engine",
    "set_tenant",
    "tenant_session",
]
