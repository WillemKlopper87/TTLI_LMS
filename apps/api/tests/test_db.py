"""Structural guarantees about the connection the app itself opens —
distinct from the RLS *policy* tests that live alongside each domain's
own test file, this is about the *role* the app connects as.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from src.core.db import assert_app_role_cannot_bypass_rls, dispose_engine, init_engine

pytestmark = pytest.mark.integration


async def test_assert_app_role_cannot_bypass_rls_passes_for_the_apps_own_connection(
    settings, database_url
) -> None:  # type: ignore[no-untyped-def]
    """L2: the app's own DATABASE_URL connects as `app_user`
    (non-superuser, non-BYPASSRLS — see the baseline migration's own
    docstring) — this must hold, or every RLS policy in the database is
    silently decorative."""
    engine = init_engine(settings)
    try:
        await assert_app_role_cannot_bypass_rls(engine)
    finally:
        await dispose_engine()


async def test_assert_app_role_cannot_bypass_rls_refuses_a_superuser_connection(
    settings, database_url
) -> None:  # type: ignore[no-untyped-def]
    """The one silent fail-open path this closes: nothing previously
    verified that DATABASE_URL isn't (mis)configured to a privileged
    role — Postgres exempts a superuser/BYPASSRLS role from every RLS
    policy unconditionally, FORCE or not, collapsing all DB-layer tenant
    isolation onto the app's own `.where(tenant_id==...)` filters alone,
    with no error anywhere. Uses the real bootstrap superuser
    (DATABASE_URL_SYNC's credentials, over the asyncpg driver) — not a
    mock — against the same test database."""
    superuser_url = settings.database_url_sync.replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    superuser_engine = create_async_engine(superuser_url)
    try:
        with pytest.raises(RuntimeError, match="bypass row-level security"):
            await assert_app_role_cannot_bypass_rls(superuser_engine)
    finally:
        await superuser_engine.dispose()
