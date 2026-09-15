"""Data-subject rights (`services/privacy.py`, BACKLOG T12).

Service-level tests pin the invariants that matter: exports are short-lived and
one-time, anonymisation never deletes the user row, and legal hold actually
blocks erasure.
"""

from __future__ import annotations

import json
import socket
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from src.core.errors import AppError, NotFound
from src.core.redis import dispose_redis, init_redis
from src.models.user import User
from src.services import privacy

pytestmark = pytest.mark.integration


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
async def redis(settings):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip("no Redis on the configured REDIS_URL")
    r = init_redis(settings)
    await r.flushdb()
    yield r
    await dispose_redis()


async def _demo_tenant_id(tenant_session_factory):  # type: ignore[no-untyped-def]
    import sqlalchemy as sa

    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _make_user(session, crypto, *, tenant_id, email: str) -> User:
    user = User(
        tenant_id=tenant_id,
        email_encrypted=crypto.encrypt(email),
        email_blind_index=crypto.blind_index(email),
        email_domain=email.rsplit("@", 1)[1],
        full_name_encrypted=crypto.encrypt("Test Person"),
        phone_encrypted=crypto.encrypt("+27 82 000 0000"),
    )
    session.add(user)
    await session.flush()
    return user


async def test_export_is_ephemeral_one_time_and_contains_profile_and_consent(
    tenant_session_factory, crypto, redis
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        user = await _make_user(
            session, crypto, tenant_id=tenant_id, email=f"export-{uuid.uuid4().hex[:8]}@example.com"
        )
        from src.services import consent as consent_service

        await consent_service.record(
            session,
            tenant_id=tenant_id,
            purpose="marketing",
            granted=True,
            source="test",
            policy_version="v1",
            user_id=user.id,
        )

        url = await privacy.build_export(
            session,
            crypto,
            redis,
            user=user,
            api_public_url="https://api.example.test",
        )

        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.example.test"
        assert parsed.path == "/api/v1/privacy/export-download"
        token = parse_qs(parsed.query)["token"][0]
        key = f"{privacy.EXPORT_KEY_PREFIX}{token}"

        ttl = await redis.ttl(key)
        assert 0 < ttl <= privacy.EXPORT_EXPIRES_IN_SECONDS

        raw = await privacy.consume_export(redis, token=token)
        body = json.loads(raw)
        assert body["profile"]["email"] == crypto.decrypt(user.email_encrypted)
        assert body["consent"][0]["purpose"] == "marketing"
        assert body["consent"][0]["granted"] is True
        assert await redis.get(key) is None

        with pytest.raises(NotFound, match="expired or has already been downloaded"):
            await privacy.consume_export(redis, token=token)


async def test_erase_user_tombstones_but_never_deletes_the_row(
    tenant_session_factory, crypto, redis
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        user = await _make_user(
            session, crypto, tenant_id=tenant_id, email=f"erase-{uuid.uuid4().hex[:8]}@example.com"
        )
        user_id = user.id

        await privacy.erase_user(
            session, crypto, redis, user=user, actor_user_id=user_id, access_token_ttl_seconds=60
        )

        refetched = await session.get(User, user_id)
        assert refetched is not None
        assert refetched.id == user_id
        assert crypto.decrypt(refetched.email_encrypted) == f"erased-{user_id}@erased.invalid"
        assert refetched.phone_encrypted is None
        assert refetched.status == "suspended"
        assert refetched.erased_at is not None


async def test_erase_user_refuses_a_second_erasure(tenant_session_factory, crypto, redis):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        user = await _make_user(
            session,
            crypto,
            tenant_id=tenant_id,
            email=f"erase-twice-{uuid.uuid4().hex[:8]}@example.com",
        )
        await privacy.erase_user(
            session, crypto, redis, user=user, actor_user_id=user.id, access_token_ttl_seconds=60
        )
        with pytest.raises(AppError, match="already been erased"):
            await privacy.erase_user(
                session,
                crypto,
                redis,
                user=user,
                actor_user_id=user.id,
                access_token_ttl_seconds=60,
            )


async def test_legal_hold_blocks_erasure(tenant_session_factory, crypto, redis):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        user = await _make_user(
            session, crypto, tenant_id=tenant_id, email=f"hold-{uuid.uuid4().hex[:8]}@example.com"
        )
        actor = await _make_user(
            session,
            crypto,
            tenant_id=tenant_id,
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        )
        actor_id = actor.id
        await privacy.set_legal_hold(
            session, user=user, reason="Active dispute, case #4471", actor_user_id=actor_id
        )

        with pytest.raises(AppError, match="legal hold"):
            await privacy.erase_user(
                session,
                crypto,
                redis,
                user=user,
                actor_user_id=user.id,
                access_token_ttl_seconds=60,
            )

        await privacy.clear_legal_hold(session, user=user, actor_user_id=actor_id)
        assert user.legal_hold is False
        assert user.legal_hold_reason is None

        await privacy.erase_user(
            session, crypto, redis, user=user, actor_user_id=user.id, access_token_ttl_seconds=60
        )


async def test_clear_legal_hold_refuses_when_none_is_set(tenant_session_factory, crypto):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        user = await _make_user(
            session, crypto, tenant_id=tenant_id, email=f"nohold-{uuid.uuid4().hex[:8]}@example.com"
        )
        with pytest.raises(AppError, match="not under legal hold"):
            await privacy.clear_legal_hold(session, user=user, actor_user_id=user.id)
