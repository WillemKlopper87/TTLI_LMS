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
from src.core.queue import dispose_queue, init_queue
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
    await init_queue(settings)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.headers["X-Tenant-Host"] = TENANT_HOST
        yield c
    await dispose_engine()
    await dispose_redis()
    await dispose_queue()


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


async def test_magic_link_request_enqueues_email_for_a_known_address(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The send itself happens on the worker (test_workers.py); here we only
    prove the request path handed it off rather than sending inline."""
    from src.core.queue import get_queue
    from src.services.email import SEND_EMAIL_JOB

    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    resp = await client.post("/api/v1/auth/magic-link", json={"email": email})
    assert resp.status_code == 204

    queued = await get_queue().queued_jobs()
    assert any(j.function == SEND_EMAIL_JOB for j in queued)


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


async def test_logout_revokes_only_this_session(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    session_a = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    session_b = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    refresh_a = session_a.json()["refresh_token"]
    refresh_b = session_b.json()["refresh_token"]

    out = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_a})
    assert out.status_code == 204

    # This session is dead...
    dead = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_a})
    assert dead.status_code == 401

    # ...but the other login's session is untouched.
    alive = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_b})
    assert alive.status_code == 200


async def test_logout_is_idempotent(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]

    first = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert first.status_code == 204
    second = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert second.status_code == 204


async def test_logout_with_unknown_token_is_still_204(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 204


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


async def test_two_tenants_resolve_to_different_themes(client) -> None:  # type: ignore[no-untyped-def]
    """The Phase 1 demo target: the same endpoint, two hostnames, two brands."""
    demo = await client.get("/api/v1/tenant/theme")  # X-Tenant-Host: localhost
    acme = await client.get("/api/v1/tenant/theme", headers={"X-Tenant-Host": "meridian.localhost"})
    assert demo.status_code == acme.status_code == 200
    assert demo.json()["tenant_slug"] == "demo"
    assert acme.json()["tenant_slug"] == "acme"
    assert demo.json()["primary_color"] != acme.json()["primary_color"]
    assert demo.json()["primary_color"] is not None


async def test_unknown_hostname_is_negative_cached(client) -> None:  # type: ignore[no-untyped-def]
    from src.core.redis import get_redis

    bogus = f"nope-{uuid.uuid4().hex[:8]}.example"
    resp = await client.get("/api/v1/auth/me", headers={"X-Tenant-Host": bogus})
    assert resp.status_code == 400  # TENANT_UNRESOLVED

    assert await get_redis().get(f"tenant:host:{bogus}") == "__miss__"


async def test_mfa_challenge_is_single_use(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    """A successful verify consumes the challenge; replaying the same
    mfa_token with a fresh valid code must not mint a second session."""
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

    first = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert first.status_code == 200

    replay = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert replay.status_code == 401


async def test_refresh_rejects_device_fingerprint_mismatch(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Device-Fingerprint": "device-a"},
    )
    refresh_token = login.json()["refresh_token"]

    wrong_device = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
        headers={"X-Device-Fingerprint": "device-b"},
    )
    assert wrong_device.status_code == 401

    # The mismatch refused the rotation without consuming or revoking:
    # the legitimate device still rotates fine.
    right_device = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
        headers={"X-Device-Fingerprint": "device-a"},
    )
    assert right_device.status_code == 200


async def test_password_reset_flow(client, tenant_session_factory, crypto, settings) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    # Request always answers 204, known address or not.
    assert (
        await client.post("/api/v1/auth/password-reset", json={"email": email})
    ).status_code == 204

    # A session that must die when the reset lands.
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    old_refresh = login.json()["refresh_token"]

    async with tenant_session_factory(tenant_id) as s:
        raw = await identity.create_password_reset(
            s, crypto, tenant_id=tenant_id, email=email, minutes=settings.password_reset_minutes
        )
    assert raw is not None

    new_password = "an entirely new passphrase 7!"
    confirm = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": new_password},
    )
    assert confirm.status_code == 204

    # Single use.
    replay = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "yet another passphrase 3!"},
    )
    assert replay.status_code == 401

    # Old password dead, old refresh-token family revoked, new password works.
    assert (
        await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    ).status_code == 200


async def test_me_carries_the_named_learner_shell_identity(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """`GET /auth/me` is the whole signed-in shell's identity payload:
    the decrypted name, a greeting-sized first name, and initials for the
    avatar — every existing field still beside them."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(
            s,
            crypto,
            tenant_id=tenant_id,
            email=email,
            password=PASSWORD,
            full_name="Thandeka Van Der Merwe",
        )

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["tenant_slug"] == "demo"
    assert body["permissions"] == []
    assert body["full_name"] == "Thandeka Van Der Merwe"
    assert body["first_name"] == "Thandeka"
    # First and last, not first and second — "TM", not "TV".
    assert body["initials"] == "TM"
    assert body["is_guest"] is False
    assert body["guest_expires_at"] is None
    assert body["guest_days_left"] is None


async def test_me_falls_back_to_the_email_when_no_name_was_ever_captured(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Checkout and guest flows never ask for a name. The avatar still
    has to render something, so initials come off the email's local part
    — but no name is fabricated for `full_name`/`first_name`."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    body = (
        await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    ).json()
    assert body["full_name"] is None
    assert body["first_name"] is None
    assert body["initials"] == email[:2].upper()


async def test_me_reports_a_guest_window_that_counts_down(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    """REQ-LEAD-06's time-limited guest account, surfaced to the client
    that has to warn about it. The window is `settings.guest_access_days`
    (Phase 0 decision #6 is still unsigned), never a hardcoded guess."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(
            s,
            crypto,
            tenant_id=tenant_id,
            email=email,
            password=PASSWORD,
            is_guest=True,
            guest_days=settings.guest_access_days,
        )

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    body = (
        await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    ).json()
    assert body["is_guest"] is True
    assert body["guest_expires_at"] is not None
    assert body["guest_days_left"] == settings.guest_access_days


async def test_mfa_pending_token_is_not_an_access_token(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The MFA challenge token is signed with the same secret and carries
    the same sub/tid claims an access token does. Before the `purpose`
    check in decode_access_token, that meant a password alone (no TOTP)
    bought a working bearer for mfa_pending_minutes — the exact bypass
    MFA exists to prevent. Regression for core/security.py."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    await _create_user(tenant_session_factory, crypto, tenant_id=tenant_id, email=email)

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    enroll = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
    secret = enroll.json()["secret"]
    code = pyotp.TOTP(secret).now()
    confirm = await client.post(
        "/api/v1/auth/mfa/enroll/confirm",
        headers=headers,
        json={"enrollment_token": enroll.json()["enrollment_token"], "code": code},
    )
    assert confirm.status_code == 200

    challenge = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert challenge.status_code == 202
    mfa_token = challenge.json()["mfa_token"]

    # A PrincipalDep endpoint with no explicit permission check — exactly
    # the surface the pre-fix token could reach.
    smuggled = await client.get(
        "/api/v1/enrolments", headers={"Authorization": f"Bearer {mfa_token}"}
    )
    assert smuggled.status_code == 401

    # The enrolment-in-progress purpose token must be refused the same way.
    fresh_enroll = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert fresh_enroll.status_code == 200
    enrollment_headers = {"Authorization": f"Bearer {fresh_enroll.json()['access_token']}"}
    re_enroll = await client.post("/api/v1/auth/mfa/enroll", headers=enrollment_headers)
    assert re_enroll.status_code == 200
    enrollment_token = re_enroll.json()["enrollment_token"]
    smuggled_enrollment = await client.get(
        "/api/v1/enrolments", headers={"Authorization": f"Bearer {enrollment_token}"}
    )
    assert smuggled_enrollment.status_code == 401
