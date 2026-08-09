"""The partitioned events table: RLS isolation and that a row actually lands
in the monthly partition its created_at implies. Raw SQL throughout, for the
same reason test_rls.py uses it — this is exactly the kind of table a
forgotten WHERE clause would leak.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration


async def _tenant_ids(factory) -> dict[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    async with factory(None) as s:
        rows = (await s.execute(sa.text("SELECT slug, id FROM tenants ORDER BY slug"))).all()
    return {r[0]: r[1] for r in rows}


_INSERT = sa.text(
    "INSERT INTO events (id, tenant_id, anonymous_id, event_name, "
    "consent_marketing, consent_analytics) "
    "VALUES (:id, :tenant_id, :anon, :name, false, true)"
)


async def test_event_lands_in_the_current_month_partition(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenants = await _tenant_ids(tenant_session_factory)
    event_id = uuid.uuid4()

    async with tenant_session_factory(tenants["demo"]) as s:
        await s.execute(
            _INSERT,
            {
                "id": event_id,
                "tenant_id": tenants["demo"],
                "anon": uuid.uuid4(),
                "name": "test.partition_probe",
            },
        )

    async with tenant_session_factory(tenants["demo"]) as s:
        partition = (
            await s.execute(
                sa.text("SELECT tableoid::regclass::text FROM events WHERE id = :id"),
                {"id": event_id},
            )
        ).scalar_one()
    assert partition.startswith("events_20")


async def test_events_are_tenant_isolated(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenants = await _tenant_ids(tenant_session_factory)

    async with tenant_session_factory(tenants["demo"]) as s:
        await s.execute(
            _INSERT,
            {
                "id": uuid.uuid4(),
                "tenant_id": tenants["demo"],
                "anon": uuid.uuid4(),
                "name": "test.tenant_isolation",
            },
        )

    async with tenant_session_factory(tenants["acme"]) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM events WHERE event_name = 'test.tenant_isolation'")
            )
        ).scalar_one()
    assert count == 0

    async with tenant_session_factory(tenants["demo"]) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM events WHERE event_name = 'test.tenant_isolation'")
            )
        ).scalar_one()
    assert count >= 1


async def test_unscoped_session_sees_no_events(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenants = await _tenant_ids(tenant_session_factory)

    async with tenant_session_factory(tenants["demo"]) as s:
        await s.execute(
            _INSERT,
            {
                "id": uuid.uuid4(),
                "tenant_id": tenants["demo"],
                "anon": uuid.uuid4(),
                "name": "test.unscoped_probe",
            },
        )

    async with tenant_session_factory(None) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM events WHERE event_name = 'test.unscoped_probe'")
            )
        ).scalar_one()
    assert count == 0
