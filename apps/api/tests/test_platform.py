"""Super-admin-only platform operations (`routers/platform.py`) — feature
flags and system health. No tests existed for this surface at all before
the 2026-09-02 audit flagged it (M2): permission denial, persistence,
unknown-flag rejection, tenant isolation and audit emission are all
exercised here for the first time.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.models.rbac import RoleAssignment
from src.services import identity

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"
PASSWORD = "correct horse battery staple 9!"


def _redis_reachable(url: str) -> bool:
    parsed = urlparse(url)
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((parsed.hostname or "localhost", parsed.port or 6379))
        return True
    except OSError:
        return False
    finally:
        sock.close()


@pytest.fixture
async def client(settings, database_url):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip(
            "no Redis on the configured REDIS_URL — run: "
            "docker compose -f infra/docker-compose.yml up -d redis"
        )
    init_engine(settings)
    redis = init_redis(settings)
    await redis.flushdb()
    await init_queue(settings)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.headers["X-Tenant-Host"] = TENANT_HOST
        yield c
    await dispose_engine()
    await dispose_redis()
    await dispose_queue()


def _unique_email() -> str:
    return f"platform-{uuid.uuid4().hex[:12]}@example.com"


async def _tenant_id(factory, slug: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with factory(None) as s:
        row = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug})
        ).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _login(client, tenant_session_factory, crypto, *, tenant_id, role: str) -> str:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        s.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role))
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def test_regular_admin_cannot_read_or_change_feature_flags(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _tenant_id(tenant_session_factory, "demo")
    # "admin" deliberately, not "super_admin" — settings:manage is seeded
    # only onto super_admin (0002_seed_roles_and_tenants.py), and the
    # sidebar/route split this permission exists for assumes a business
    # admin can never reach this surface even with a valid token.
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )

    get_resp = await client.get(
        "/api/v1/platform/feature-flags", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert get_resp.status_code == 403

    patch_resp = await client.patch(
        "/api/v1/platform/feature-flags/podcasts",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"enabled": False},
    )
    assert patch_resp.status_code == 403

    health_resp = await client.get(
        "/api/v1/platform/system-health", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert health_resp.status_code == 403


async def test_flags_default_enabled_and_system_health_reports_dependencies(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _tenant_id(tenant_session_factory, "demo")
    token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    flags_resp = await client.get(
        "/api/v1/platform/feature-flags", headers={"Authorization": f"Bearer {token}"}
    )
    assert flags_resp.status_code == 200, flags_resp.text
    flags = {f["key"]: f for f in flags_resp.json()["flags"]}
    assert "podcasts" in flags
    assert all(f["enabled"] is True for f in flags.values())

    health_resp = await client.get(
        "/api/v1/platform/system-health", headers={"Authorization": f"Bearer {token}"}
    )
    assert health_resp.status_code == 200, health_resp.text
    services = {s["name"]: s["ok"] for s in health_resp.json()["services"]}
    assert services["database"] is True
    assert services["redis"] is True


async def test_toggling_a_flag_persists_and_can_be_reversed(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _tenant_id(tenant_session_factory, "demo")
    token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    off = await client.patch(
        "/api/v1/platform/feature-flags/workshops",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert off.status_code == 200, off.text
    flags = {f["key"]: f["enabled"] for f in off.json()["flags"]}
    assert flags["workshops"] is False

    reread = await client.get(
        "/api/v1/platform/feature-flags", headers={"Authorization": f"Bearer {token}"}
    )
    flags = {f["key"]: f["enabled"] for f in reread.json()["flags"]}
    assert flags["workshops"] is False

    on = await client.patch(
        "/api/v1/platform/feature-flags/workshops",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
    assert on.status_code == 200, on.text
    flags = {f["key"]: f["enabled"] for f in on.json()["flags"]}
    assert flags["workshops"] is True


async def test_unknown_flag_key_is_rejected(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _tenant_id(tenant_session_factory, "demo")
    token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    resp = await client.patch(
        "/api/v1/platform/feature-flags/not-a-real-flag",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert resp.status_code == 400


async def test_flag_change_is_tenant_isolated(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    demo_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=demo_id, role="super_admin"
    )

    off = await client.patch(
        "/api/v1/platform/feature-flags/subscriptions",
        headers={"Authorization": f"Bearer {demo_token}"},
        json={"enabled": False},
    )
    assert off.status_code == 200, off.text
    try:
        async with tenant_session_factory(acme_id) as s:
            acme_flags = (
                await s.execute(
                    sa.text("SELECT feature_flags FROM tenants WHERE id = :id"), {"id": acme_id}
                )
            ).scalar_one()
    finally:
        # demo's tenant row is shared, session-lived state used by every
        # other subscriptions test — leaving this off after the test ends
        # broke test_subscriptions.py entirely the first time this ran as
        # part of the full suite, not in isolation.
        await client.patch(
            "/api/v1/platform/feature-flags/subscriptions",
            headers={"Authorization": f"Bearer {demo_token}"},
            json={"enabled": True},
        )
    # acme's own settings row must be untouched — "subscriptions" either
    # absent entirely (never written) or still true, never demo's False.
    assert acme_flags.get("subscriptions", True) is True


async def test_flag_change_is_audited(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _tenant_id(tenant_session_factory, "demo")
    token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    resp = await client.patch(
        "/api/v1/platform/feature-flags/podcasts",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": False},
    )
    assert resp.status_code == 200, resp.text

    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text(
                    "SELECT before, after FROM audit_events "
                    "WHERE tenant_id = :tid AND action = 'tenant.setting.changed' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tid": tenant_id},
            )
        ).first()
    assert row is not None, "expected an audit_events row for the flag change"
    _before, after = row
    assert after.get("podcasts") is False

    # Restore, so this test doesn't leak a disabled flag into whatever
    # runs next against the shared demo tenant.
    await client.patch(
        "/api/v1/platform/feature-flags/podcasts",
        headers={"Authorization": f"Bearer {token}"},
        json={"enabled": True},
    )
