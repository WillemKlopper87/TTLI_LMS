"""Tenant isolation, asserted against the database rather than the ORM.

These are the tests that justify row-level security existing at all: they run
raw SQL with no tenant filter in the WHERE clause, exactly as a careless
reporting query would, and assert that Postgres still refuses to hand rows over.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, ProgrammingError

pytestmark = pytest.mark.integration


async def _tenant_ids(factory) -> dict[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    async with factory(None) as s:
        rows = (await s.execute(sa.text("SELECT slug, id FROM tenants ORDER BY slug"))).all()
    return {r[0]: r[1] for r in rows}


async def test_seed_created_two_tenants(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenants = await _tenant_ids(tenant_session_factory)
    assert {"acme", "demo"} <= set(tenants)


async def test_tenants_table_is_readable_without_a_tenant(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    """Hostname resolution runs before a tenant is known, so this table has no RLS."""
    async with tenant_session_factory(None) as s:
        count = (await s.execute(sa.text("SELECT count(*) FROM tenant_domains"))).scalar_one()
    assert count >= 2


async def test_unscoped_session_sees_no_users(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    """Fails closed: with no tenant set the policy matches nothing."""
    async with tenant_session_factory(None) as s:
        count = (await s.execute(sa.text("SELECT count(*) FROM users"))).scalar_one()
    assert count == 0


async def test_each_tenant_sees_only_its_own_users(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenants = await _tenant_ids(tenant_session_factory)

    async with tenant_session_factory(tenants["demo"]) as s:
        demo_rows = (await s.execute(sa.text("SELECT tenant_id FROM users"))).scalars().all()
    async with tenant_session_factory(tenants["acme"]) as s:
        acme_rows = (await s.execute(sa.text("SELECT tenant_id FROM users"))).scalars().all()

    # No WHERE clause anywhere above. Postgres did the filtering.
    assert all(t == tenants["demo"] for t in demo_rows)
    assert all(t == tenants["acme"] for t in acme_rows)


async def test_cannot_read_another_tenants_row_by_id(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    """The classic IDOR: a known primary key from the wrong tenant returns nothing."""
    tenants = await _tenant_ids(tenant_session_factory)

    async with tenant_session_factory(tenants["demo"]) as s:
        victim = (await s.execute(sa.text("SELECT id FROM users LIMIT 1"))).scalar_one_or_none()
    if victim is None:
        pytest.skip("no seeded user in the demo tenant")

    async with tenant_session_factory(tenants["acme"]) as s:
        found = (
            await s.execute(sa.text("SELECT id FROM users WHERE id = :i"), {"i": victim})
        ).scalar_one_or_none()
    assert found is None


async def test_cannot_insert_a_row_for_another_tenant(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    """WITH CHECK: a session scoped to A cannot plant a row belonging to B."""
    tenants = await _tenant_ids(tenant_session_factory)

    with pytest.raises((DBAPIError, ProgrammingError)):
        async with tenant_session_factory(tenants["demo"]) as s:
            await s.execute(
                sa.text(
                    "INSERT INTO users (id, tenant_id, email_encrypted, email_blind_index, "
                    "email_domain) VALUES (:i, :t, :e, :b, 'example.com')"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": tenants["acme"],
                    "e": b"x",
                    "b": uuid.uuid4().bytes,
                },
            )


async def test_audit_events_refuse_update(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenants = await _tenant_ids(tenant_session_factory)

    async with tenant_session_factory(tenants["demo"]) as s:
        await s.execute(
            sa.text(
                "INSERT INTO audit_events (id, tenant_id, action) VALUES (:i, :t, 'test.probe')"
            ),
            {"i": uuid.uuid4(), "t": tenants["demo"]},
        )

    with pytest.raises(DBAPIError, match="append_only_violation"):
        async with tenant_session_factory(tenants["demo"]) as s:
            await s.execute(
                sa.text("UPDATE audit_events SET action = 'tampered' WHERE action = 'test.probe'")
            )


async def test_audit_events_refuse_delete(tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenants = await _tenant_ids(tenant_session_factory)
    with pytest.raises(DBAPIError, match="append_only_violation"):
        async with tenant_session_factory(tenants["demo"]) as s:
            await s.execute(sa.text("DELETE FROM audit_events WHERE action = 'test.probe'"))
