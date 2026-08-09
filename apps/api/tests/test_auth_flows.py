"""End-to-end HTTP coverage for Sprint 2: magic links, TOTP, refresh rotation.

Runs against the real ASGI app and a live Postgres, so tenancy, RLS and the
app_user grants are all genuinely exercised — the same reason test_rls.py
runs raw SQL instead of going through the ORM.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text
from src.core.db import dispose_engine, init_engine
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.services import identity

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"  # the "demo" tenant's seeded primary hostname
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


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa_text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _create_user(  # type: ignore[no-untyped-def]
    tenant_session_factory, crypto, *, tenant_id: uuid.UUID, email: str
) -> uuid.UUID:
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        user_id = user.id
    return user_id


@pytest.fixture
async def client(settings, database_url):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip(
            "no Redis on the configured REDIS_URL — run: "
            "docker compose -f infra/docker-compose.yml up -d redis"
        )
    init_engine(settings)
    redis = init_redis(settings)
    # Full flush, not a targeted delete: this Redis instance is dedicated to
    # this project (infra/docker-compose.yml), so wiping it between tests is
    # the simplest way to keep rate-limit counters and the tenant cache from
    # bleeding across test runs.
    await redis.flushdb()
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.headers["X-Tenant-Host"] = TENANT_HOST
        yield c
    await dispose_engine()
    await dispose_redis()


def _unique_email() -> str:
    return f"sprint2-{uuid.uuid4().hex[:12]}@example.com"


async def test_login_issues_access_and_refresh_tokens(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_magic_link_consume_issues_tokens(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    async with tenant_session_factory(tenant_id) as s:
        raw = await identity.create_magic_link(
            s, crypto, tenant_id=tenant_id, email=email, minutes=settings.magic_link_minutes
        )
    assert raw is not None

    resp = await client.post("/api/v1/auth/magic-link/consume", json={"token": raw})
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    # Single use: the same link fails the second time.
    replay = await client.post("/api/v1/auth/magic-link/consume", json={"token": raw})
    assert replay.status_code == 401


async def test_magic_link_request_always_returns_204_for_unknown_address(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/auth/magic-link", json={"email": _unique_email()})
    assert resp.status_code == 204


async def test_totp_enroll_and_login_challenge(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    enroll = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    enrollment_token = enroll.json()["enrollment_token"]

    code = pyotp.TOTP(secret).now()
    confirm = await client.post(
        "/api/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"enrollment_token": enrollment_token, "code": code},
    )
    assert confirm.status_code == 200
    recovery_codes = confirm.json()["recovery_codes"]
    assert len(recovery_codes) == 10

    # MFA is now required: login returns a challenge, not tokens.
    second_login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert second_login.status_code == 202
    challenge = second_login.json()
    assert challenge["mfa_required"] is True
    mfa_token = challenge["mfa_token"]

    verify = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert verify.status_code == 200
    assert verify.json()["access_token"]


async def test_mfa_recovery_code_is_single_use(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    enroll = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret, enrollment_token = enroll.json()["secret"], enroll.json()["enrollment_token"]
    confirm = await client.post(
        "/api/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"enrollment_token": enrollment_token, "code": pyotp.TOTP(secret).now()},
    )
    recovery_code = confirm.json()["recovery_codes"][0]

    challenge = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).json()

    first = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": challenge["mfa_token"], "code": recovery_code},
    )
    assert first.status_code == 200

    challenge2 = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).json()
    replay = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": challenge2["mfa_token"], "code": recovery_code},
    )
    assert replay.status_code == 401


async def test_mfa_locks_after_six_failures(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    enroll = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret, enrollment_token = enroll.json()["secret"], enroll.json()["enrollment_token"]
    await client.post(
        "/api/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"enrollment_token": enrollment_token, "code": pyotp.TOTP(secret).now()},
    )

    challenge = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).json()
    mfa_token = challenge["mfa_token"]

    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"}
        )
        assert resp.status_code == 401

    sixth = await client.post(
        "/api/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "code": "000000"}
    )
    assert sixth.status_code == 429

    # Locked out even with the correct code now.
    locked = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert locked.status_code == 429


async def test_refresh_rotates_and_detects_reuse(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    refresh_1 = login.json()["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
    assert rotated.status_code == 200
    refresh_2 = rotated.json()["refresh_token"]
    assert refresh_2 != refresh_1

    # Reusing the consumed token is the theft signal: it fails...
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1})
    assert reuse.status_code == 401

    # ...and revokes the whole family, including the token issued above.
    also_revoked = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_2})
    assert also_revoked.status_code == 401


async def test_login_rate_limits_by_account(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    """03_API_SPEC.md §1.8: 5/min per account."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
        )
        assert resp.status_code == 401

    sixth = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert sixth.status_code == 429

    # The account is rate-limited even with the correct password now.
    locked = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 429


async def test_login_rate_limits_by_ip_across_accounts(client) -> None:  # type: ignore[no-untyped-def]
    """03_API_SPEC.md §1.8: 10/min per IP — a different account each time, so
    the per-account limit (5/min) never trips and only the per-IP one can."""
    for _ in range(10):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": _unique_email(), "password": "wrong-password"}
        )
        assert resp.status_code == 401

    eleventh = await client.post(
        "/api/v1/auth/login", json={"email": _unique_email(), "password": "wrong-password"}
    )
    assert eleventh.status_code == 429


async def test_tenant_resolution_is_cached_in_redis(client) -> None:  # type: ignore[no-untyped-def]
    from src.core.redis import get_redis

    resp = await client.get("/api/v1/auth/me")  # any endpoint that resolves a tenant
    assert resp.status_code == 401  # unauthenticated — resolving the tenant still ran

    cached = await get_redis().get(f"tenant:host:{TENANT_HOST}")
    assert cached is not None
    assert TENANT_HOST in cached
