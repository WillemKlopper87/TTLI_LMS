"""Guest account provisioning (03 §4.2, REQ-LEAD-04..07): HTTP coverage,
plus raw-SQL checks on users/magic_links — the same reason test_leads.py and
test_rls.py go around the ORM.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.services import identity

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"


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
    return f"guest-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


def _body(email: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "email": email,
        "first_name": "Grace",
        "last_name": "Hopper",
        "privacy_consent": True,
        "marketing_consent": False,
    }
    body.update(overrides)
    return body


async def _guest_row(
    tenant_session_factory, crypto, *, tenant_id, email
) -> tuple[uuid.UUID, bool, object]:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text(
                    "SELECT id, is_guest, guest_expires_at FROM users "
                    "WHERE email_blind_index = :idx"
                ),
                {"idx": crypto.blind_index(email)},
            )
        ).first()
    assert row is not None
    return uuid.UUID(str(row[0])), bool(row[1]), row[2]


async def test_guest_access_returns_204(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/guest-access", json=_body(_unique_email()))
    assert resp.status_code == 204


async def test_guest_access_without_privacy_consent_is_rejected(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/guest-access", json=_body(_unique_email(), privacy_consent=False)
    )
    assert resp.status_code == 400


async def test_guest_access_creates_a_time_limited_guest_user(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()

    resp = await client.post("/api/v1/guest-access", json=_body(email))
    assert resp.status_code == 204

    _, is_guest, guest_expires_at = await _guest_row(
        tenant_session_factory, crypto, tenant_id=tenant_id, email=email
    )
    assert is_guest is True
    assert guest_expires_at is not None
    expected = datetime.now(UTC) + timedelta(days=settings.guest_access_days)
    assert abs((guest_expires_at - expected).total_seconds()) < 60


async def test_guest_access_sends_a_magic_link(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()

    resp = await client.post("/api/v1/guest-access", json=_body(email))
    assert resp.status_code == 204

    user_id, _, _ = await _guest_row(
        tenant_session_factory, crypto, tenant_id=tenant_id, email=email
    )
    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM magic_links WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar_one()
    assert count >= 1


async def test_guest_access_twice_reuses_the_same_guest(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()

    first = await client.post("/api/v1/guest-access", json=_body(email))
    assert first.status_code == 204
    second = await client.post("/api/v1/guest-access", json=_body(email, last_name="Hopper-Murray"))
    assert second.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        rows = (
            await s.execute(
                sa.text("SELECT id FROM users WHERE email_blind_index = :idx"),
                {"idx": crypto.blind_index(email)},
            )
        ).all()
    # REQ-LEAD-04: unique per lead — a repeat request refreshes the same
    # account rather than minting a second one.
    assert len(rows) == 1


async def test_guest_access_does_not_downgrade_an_existing_full_account(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password="correct horse battery staple 9!"
        )

    resp = await client.post("/api/v1/guest-access", json=_body(email))
    assert resp.status_code == 204

    _, is_guest, guest_expires_at = await _guest_row(
        tenant_session_factory, crypto, tenant_id=tenant_id, email=email
    )
    assert is_guest is False
    assert guest_expires_at is None


async def test_expired_guest_cannot_consume_a_magic_link(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, is_guest=True, guest_days=-1
        )
        raw = await identity.create_magic_link(
            s, crypto, tenant_id=tenant_id, email=email, minutes=settings.magic_link_minutes
        )
        assert raw is not None
        assert user.guest_expires_at is not None
        assert user.guest_expires_at < datetime.now(UTC)

    resp = await client.post("/api/v1/auth/magic-link/consume", json={"token": raw})
    assert resp.status_code == 401


async def test_expired_guest_cannot_refresh(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, is_guest=True, guest_days=1
        )
        raw = await identity.create_magic_link(
            s, crypto, tenant_id=tenant_id, email=email, minutes=settings.magic_link_minutes
        )
        assert raw is not None

    consumed = await client.post("/api/v1/auth/magic-link/consume", json={"token": raw})
    assert consumed.status_code == 200
    refresh_token = consumed.json()["refresh_token"]

    # The guest's window closes after the token was issued — same shape as
    # a legitimate session outliving a short guest trial.
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text("UPDATE users SET guest_expires_at = :past WHERE email_blind_index = :idx"),
            {"past": datetime.now(UTC) - timedelta(minutes=1), "idx": crypto.blind_index(email)},
        )

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401


async def test_expired_guest_cannot_use_an_already_issued_access_token(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    """L9: expiry was only ever checked at the two points a guest crosses
    a boundary (consuming a magic link, rotating a refresh token) — an
    access token minted just before `guest_expires_at` kept working for
    up to its own full lifetime (`access_token_minutes`) after the guest
    window closed, with no check in `core/deps.get_principal` at all.

    The fix stamps the access token with the guest's `guest_expires_at`
    at issue time and has `get_principal` compare it to wall-clock
    `now()` — the same shape a JWT's own `exp` claim already uses, and
    deliberately not a live re-read of the database (unlike `/auth/
    refresh`'s check, which piggybacks on a DB round-trip refresh needs
    anyway): `get_principal` runs on every authenticated request in the
    app, and adding a database read to it is a materially bigger,
    riskier change than this finding's severity justifies. That
    difference is exactly why this test uses a real, short sleep to let
    wall-clock time pass the value already baked into the token — a
    raw-SQL edit afterwards (`test_expired_guest_cannot_refresh`'s own
    trick) wouldn't reach a claim that was already minted."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, is_guest=True, guest_days=1
        )
        # Near-future, not already past: consume_magic_link itself refuses
        # a guest whose window has already closed, so this has to still be
        # open at consume time and close shortly after.
        await s.execute(
            sa.text("UPDATE users SET guest_expires_at = :soon WHERE email_blind_index = :idx"),
            {"soon": datetime.now(UTC) + timedelta(seconds=2), "idx": crypto.blind_index(email)},
        )
        raw = await identity.create_magic_link(
            s, crypto, tenant_id=tenant_id, email=email, minutes=settings.magic_link_minutes
        )
        assert raw is not None

    consumed = await client.post("/api/v1/auth/magic-link/consume", json={"token": raw})
    assert consumed.status_code == 200
    access_token = consumed.json()["access_token"]

    # The access token's signature is still valid and it has not expired
    # on its own schedule — only the guest window closing makes it dead.
    before = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert before.status_code == 200

    await asyncio.sleep(2.5)

    after = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert after.status_code == 401
