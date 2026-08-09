"""The maintenance jobs, run exactly as the worker runs them: through the
SECURITY DEFINER functions, over an app_user connection with no tenant bound.
That combination is the point — the jobs must work despite RLS and without
DDL privileges of their own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from src.core.db import dispose_engine, init_engine
from src.models.auth import RefreshToken
from src.workers.main import extend_event_partitions, purge_expired_auth

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine(settings, database_url):  # type: ignore[no-untyped-def]
    init_engine(settings)
    yield
    await dispose_engine()


async def test_extend_event_partitions_is_idempotent_and_extends(
    engine, tenant_session_factory
) -> None:  # type: ignore[no-untyped-def]
    created_first = await extend_event_partitions({})
    # 0004 already bootstrapped ~13 months, so a second run creates nothing.
    created_second = await extend_event_partitions({})
    assert created_second == 0
    assert created_first >= 0

    async with tenant_session_factory(None) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'events'::regclass")
            )
        ).scalar_one()
    assert count >= 13


async def test_purge_deletes_only_rows_past_the_grace_period(
    engine, tenant_session_factory
) -> None:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        tenant_id = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))
        ).scalar_one()

    now = datetime.now(UTC)
    old_hash = uuid.uuid4().bytes + uuid.uuid4().bytes  # 32 unique bytes
    fresh_hash = uuid.uuid4().bytes + uuid.uuid4().bytes

    async with tenant_session_factory(tenant_id) as s:
        user_id = (await s.execute(sa.text("SELECT id FROM users LIMIT 1"))).scalar_one()
        s.add(
            RefreshToken(
                tenant_id=tenant_id,
                user_id=user_id,
                family_id=uuid.uuid4(),
                token_hash=old_hash,
                expires_at=now - timedelta(days=40),
            )
        )
        s.add(
            RefreshToken(
                tenant_id=tenant_id,
                user_id=user_id,
                family_id=uuid.uuid4(),
                token_hash=fresh_hash,
                expires_at=now + timedelta(days=1),
            )
        )

    purged = await purge_expired_auth({})
    assert purged >= 1

    async with tenant_session_factory(tenant_id) as s:
        remaining = (
            (
                await s.execute(
                    sa.text("SELECT token_hash FROM refresh_tokens WHERE token_hash IN (:a, :b)"),
                    {"a": old_hash, "b": fresh_hash},
                )
            )
            .scalars()
            .all()
        )
    assert old_hash not in remaining
    assert fresh_hash in remaining
