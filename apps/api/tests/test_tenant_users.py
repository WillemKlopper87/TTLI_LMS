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

# A minimal real PNG header; the endpoint validates the declared content
# type, not the magic bytes, but a plausible payload keeps the test honest.
_PNG_BYTES = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"0" * 64


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


async def test_suspending_a_user_kills_their_sessions_immediately(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """H-11: `set_status` used to only flip the status column — an
    already-issued access token kept working until it happened to expire,
    and the refresh token kept rotating right past the suspension. Both
    must die the moment status leaves `active`, not on their own schedule.
    """
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    admin_headers = {"Authorization": f"Bearer {boss}"}

    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        target = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        target_id = target.id

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]
    learner_headers = {"Authorization": f"Bearer {access_token}"}

    # Both are live before suspension.
    assert (await client.get("/api/v1/auth/me", headers=learner_headers)).status_code == 200

    suspend = await client.post(
        f"/api/v1/tenant/users/{target_id}/status",
        json={"status": "suspended"},
        headers=admin_headers,
    )
    assert suspend.status_code == 204, suspend.text

    # The access token's signature is still valid and it has not expired —
    # only the suspension makes it dead now.
    dead_access = await client.get("/api/v1/auth/me", headers=learner_headers)
    assert dead_access.status_code == 401

    dead_refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert dead_refresh.status_code == 401

    # Login itself is refused outright while suspended.
    relogin = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert relogin.status_code == 401


async def test_reinstating_a_suspended_user_restores_access(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Flipping status back to active must let a fresh login mint tokens
    that work — and a token minted after reinstatement must not be caught
    by the suspension's revocation mark."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    admin_headers = {"Authorization": f"Bearer {boss}"}

    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        target = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        target_id = target.id

    await client.post(
        f"/api/v1/tenant/users/{target_id}/status",
        json={"status": "suspended"},
        headers=admin_headers,
    )
    suspended_login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert suspended_login.status_code == 401

    reinstate = await client.post(
        f"/api/v1/tenant/users/{target_id}/status",
        json={"status": "active"},
        headers=admin_headers,
    )
    assert reinstate.status_code == 204, reinstate.text

    relogin = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert relogin.status_code == 200, relogin.text
    new_access = relogin.json()["access_token"]

    restored = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert restored.status_code == 200


async def test_role_revocation_is_reflected_on_the_next_refresh(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Permissions are baked into the access token at issuance, not looked
    up per request. `refresh` re-fetches them from the database on every
    rotation (`routers/auth.py`), so revoking a role must be visible in the
    very next refreshed token rather than waiting for the old one's full
    natural expiry."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    admin_headers = {"Authorization": f"Bearer {boss}"}

    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        target = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        target_id = target.id
        s.add(RoleAssignment(tenant_id=tenant_id, user_id=target_id, role_code="content_author"))

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    before_me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert before_me.status_code == 200
    granted_permissions = set(before_me.json()["permissions"])
    assert granted_permissions, "content_author must carry at least one permission"

    revoke = await client.delete(
        f"/api/v1/tenant/users/{target_id}/roles/content_author", headers=admin_headers
    )
    assert revoke.status_code == 204

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200, rotated.text

    after_me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert after_me.status_code == 200
    assert set(after_me.json()["permissions"]).isdisjoint(granted_permissions)


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


async def test_branding_refuses_a_colour_nobody_can_read(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """A tenant picking its own brand colour can trivially produce
    white-on-yellow buttons. This platform holds a WCAG AA line that an
    axe gate enforces on every public page, so the colour is measured
    against the text that will sit on it and refused below 4.5:1 — with
    the ratio in the message, because "invalid" tells a designer
    nothing."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {boss}"}

    bad = await client.patch(
        "/api/v1/tenant/branding", json={"primary_color": "#ffe600"}, headers=headers
    )
    assert bad.status_code == 400
    body = bad.json()["error"]
    assert body["details"]["contrast"] < 4.5
    assert "4.5" in body["message"]

    malformed = await client.patch(
        "/api/v1/tenant/branding", json={"primary_color": "red"}, headers=headers
    )
    assert malformed.status_code == 400

    # A dark brand colour carries light text comfortably and is accepted.
    good = await client.patch(
        "/api/v1/tenant/branding",
        json={"primary_color": "#8e151c", "support_email": "help@example.com"},
        headers=headers,
    )
    assert good.status_code == 200, good.text
    assert good.json()["primary_color"] == "#8e151c"

    # Absent fields are left alone rather than blanked by omission.
    partial = await client.patch(
        "/api/v1/tenant/branding", json={"email_footer_text": "Sent by TTLI"}, headers=headers
    )
    assert partial.status_code == 200
    assert partial.json()["support_email"] == "help@example.com"


async def test_branding_needs_tenant_manage(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}
    assert (await client.get("/api/v1/tenant/branding", headers=headers)).status_code == 403
    assert (
        await client.patch(
            "/api/v1/tenant/branding", json={"primary_color": "#8e151c"}, headers=headers
        )
    ).status_code == 403


async def test_domains_are_globally_unique_and_the_primary_one_is_protected(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """A hostname is how a request finds its tenant, so two tenants
    cannot hold one; and removing the primary would take the tenant off
    the internet from a settings screen."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {boss}"}
    hostname = f"p3-{uuid.uuid4().hex[:10]}.example.com"

    added = await client.post(
        "/api/v1/tenant/domains", json={"hostname": hostname}, headers=headers
    )
    assert added.status_code == 201, added.text
    row = added.json()
    assert row["hostname"] == hostname
    assert row["verified_at"] is None, "a new hostname is never born verified"
    assert row["tls_status"] == "pending"
    assert row["dns_txt_record"].startswith("ttli-verify=")

    duplicate = await client.post(
        "/api/v1/tenant/domains", json={"hostname": hostname.upper()}, headers=headers
    )
    assert duplicate.status_code == 400

    rubbish = await client.post(
        "/api/v1/tenant/domains", json={"hostname": "not a hostname"}, headers=headers
    )
    assert rubbish.status_code == 400

    listing = await client.get("/api/v1/tenant/domains", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    # Stated rather than implied: nothing here can mark a domain verified.
    assert body["verification_available"] is False
    primary = next((d for d in body["items"] if d["is_primary"]), None)
    assert primary is not None, "the demo tenant has a primary hostname"

    protected = await client.delete(f"/api/v1/tenant/domains/{primary['id']}", headers=headers)
    assert protected.status_code == 400

    removed = await client.delete(f"/api/v1/tenant/domains/{row['id']}", headers=headers)
    assert removed.status_code == 204


async def test_a_logo_upload_refuses_svg_and_ignores_the_client_filename(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Both halves of a security-review finding on this endpoint
    (2026-08-21). SVG is a script-carrying format served from a public
    container, and "an administrator uploaded it" is not a reason to
    host active content. The stored key takes nothing from the client
    either — extension from the validated content type, fixed stem."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {boss}"}

    svg = await client.post(
        "/api/v1/tenant/branding/logo",
        headers=headers,
        files={"file": ("logo.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml")},
    )
    assert svg.status_code == 400
    assert "SVG" not in svg.json()["error"]["message"], "the message lists what IS allowed"

    # A PNG whose filename tries to traverse still lands under this
    # tenant's own prefix, named for its type.
    png = await client.post(
        "/api/v1/tenant/branding/logo",
        headers=headers,
        files={"file": ("../../evil.png", _PNG_BYTES, "image/png")},
    )
    assert png.status_code == 200, png.text
    key = png.json()["logo_url"]
    assert key == f"tenant-branding/{tenant_id}/logo.png"
    assert ".." not in key
