"""Staff administration (`routers/tenant_users.py`, backlog P3).

The escalation rule is what these tests exist for. Everything else here
is ordinary CRUD; "an admin cannot mint a super_admin and act through
them" is the invariant that makes the whole permission model mean
something, so it gets the most direct test in the file.
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
        pytest.skip("no Redis on the configured REDIS_URL")
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
    return f"staff-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _login(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, *, tenant_id, role: str | None
) -> tuple[str, uuid.UUID]:
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        user_id = user.id
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user_id, role_code=role))
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"]), user_id


async def test_an_admin_cannot_grant_a_role_that_outranks_them(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The invariant the whole module exists to hold. `admin` holds
    `user:invite` and `user:suspend` but not `tenant:manage`, so it is
    refused at the permission gate; even a caller who *did* hold
    `tenant:manage` could not grant `super_admin` unless they already
    held every permission it carries."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    target_email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        target = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=target_email, password=PASSWORD
        )
        target_id = target.id

    resp = await client.post(
        f"/api/v1/tenant/users/{target_id}/roles",
        json={"role_code": "super_admin"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 403

    # And the assignment really did not happen.
    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM role_assignments WHERE user_id = :u"),
                {"u": target_id},
            )
        ).scalar_one()
    assert count == 0


async def test_a_super_admin_grants_and_revokes_a_role_and_both_are_audited(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {boss}"}
    async with tenant_session_factory(tenant_id) as s:
        target = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=_unique_email(), password=PASSWORD
        )
        target_id = target.id

    granted = await client.post(
        f"/api/v1/tenant/users/{target_id}/roles",
        json={"role_code": "content_author"},
        headers=headers,
    )
    assert granted.status_code == 204, granted.text

    # Granting twice is a no-op, not an error.
    again = await client.post(
        f"/api/v1/tenant/users/{target_id}/roles",
        json={"role_code": "content_author"},
        headers=headers,
    )
    assert again.status_code == 204

    listing = await client.get("/api/v1/tenant/users", headers=headers)
    assert listing.status_code == 200, listing.text
    row = next(r for r in listing.json()["items"] if r["id"] == str(target_id))
    assert row["roles"] == ["content_author"]

    revoked = await client.delete(
        f"/api/v1/tenant/users/{target_id}/roles/content_author", headers=headers
    )
    assert revoked.status_code == 204

    # The audit constants existed since 0001 and nothing could emit them
    # until this pass; both directions must now appear.
    log = await client.get(f"/api/v1/audit-events?entity_id={target_id}&limit=25", headers=headers)
    assert log.status_code == 200
    actions = {row["action"] for row in log.json()["items"]}
    assert "rbac.role.assigned" in actions
    assert "rbac.role.revoked" in actions


async def test_nobody_changes_their_own_roles_or_status(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Revoking your own last `tenant:manage` would lock the tenant out
    of its own administration with no in-product way back."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, boss_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {boss}"}

    self_grant = await client.post(
        f"/api/v1/tenant/users/{boss_id}/roles",
        json={"role_code": "finance"},
        headers=headers,
    )
    assert self_grant.status_code == 403

    self_revoke = await client.delete(
        f"/api/v1/tenant/users/{boss_id}/roles/super_admin", headers=headers
    )
    assert self_revoke.status_code == 403

    self_suspend = await client.post(
        f"/api/v1/tenant/users/{boss_id}/status",
        json={"status": "suspended"},
        headers=headers,
    )
    assert self_suspend.status_code == 403


async def test_inviting_a_colleague_creates_a_passwordless_account(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """An administrator never handles someone else's password: the
    account is created without one and the invitee arrives by magic
    link."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {boss}"}
    email = _unique_email()

    resp = await client.post(
        "/api/v1/tenant/users",
        json={"email": email, "full_name": "New Colleague", "roles": ["finance"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["roles"] == ["finance"]

    async with tenant_session_factory(tenant_id) as s:
        password_hash = (
            await s.execute(
                sa.text("SELECT password_hash FROM users WHERE id = :u"), {"u": body["id"]}
            )
        ).scalar_one()
    assert password_hash is None, "an invited account must have no password set"

    # Inviting the same address twice is refused rather than silently
    # creating a second account for one person.
    duplicate = await client.post("/api/v1/tenant/users", json={"email": email}, headers=headers)
    assert duplicate.status_code == 400


async def test_a_learner_sees_none_of_this(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    headers = {"Authorization": f"Bearer {learner}"}

    assert (await client.get("/api/v1/tenant/users", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/tenant/roles", headers=headers)).status_code == 403
    assert (
        await client.post("/api/v1/tenant/users", json={"email": _unique_email()}, headers=headers)
    ).status_code == 403


async def test_roles_list_explains_what_each_role_confers(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    resp = await client.get("/api/v1/tenant/roles", headers={"Authorization": f"Bearer {admin}"})
    assert resp.status_code == 200, resp.text
    roles = {r["code"]: r for r in resp.json()["roles"]}
    assert "super_admin" in roles and "learner" in roles
    # A code alone tells an administrator nothing; the permission list is
    # what lets the screen explain the choice.
    assert "audit:read" in roles["admin"]["permissions"]
    assert roles["learner"]["permissions"] == ["course:view", "lesson:complete"]
