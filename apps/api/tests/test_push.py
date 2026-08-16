"""Web Push subscription management and delivery (01 §5.9) — the HTTP
surface (subscribe upserts on repeat endpoint, unsubscribe only ever
touches the caller's own row, the VAPID public key endpoint), and
`send_push_sync`'s exception classification (a dead-endpoint 404/410
becomes `PushSubscriptionGone`, anything else propagates unchanged) —
tested by substituting `pywebpush.webpush` itself, the one boundary with
no live push service to test against, the same "keep everything else
real" principle `test_payments_payfast.py`'s scripted subclass already
established for a different unverifiable external call.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from pywebpush import WebPushException
from src.core.db import dispose_engine, init_engine
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.services import push as push_service

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
    return f"push-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _login(client, tenant_session_factory, crypto, *, tenant_id) -> str:  # type: ignore[no-untyped-def]
    from src.services import identity

    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD)
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


def _subscribe_body(endpoint: str) -> dict:  # type: ignore[type-arg]
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": "fake-p256dh-key", "auth": "fake-auth-key"},
    }


async def test_subscribe_creates_and_upserts_on_repeat_endpoint(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    endpoint = f"https://push.example.com/{uuid.uuid4().hex}"

    first = await client.post(
        "/api/v1/push-subscriptions",
        json=_subscribe_body(endpoint),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/push-subscriptions",
        json=_subscribe_body(endpoint),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 201, second.text
    # Same endpoint upserts the same row rather than duplicating it.
    assert second.json()["id"] == first.json()["id"]

    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM push_subscriptions WHERE endpoint = :e"),
                {"e": endpoint},
            )
        ).scalar_one()
    assert count == 1


async def test_unsubscribe_ignores_another_users_subscription(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    owner_token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    other_token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    endpoint = f"https://push.example.com/{uuid.uuid4().hex}"

    created = await client.post(
        "/api/v1/push-subscriptions",
        json=_subscribe_body(endpoint),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    subscription_id = created.json()["id"]

    # A different user's delete request is a silent no-op, not a leak of
    # whether the id exists.
    resp = await client.delete(
        f"/api/v1/push-subscriptions/{subscription_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        still_there = (
            await s.execute(
                sa.text("SELECT count(*) FROM push_subscriptions WHERE id = :i"),
                {"i": subscription_id},
            )
        ).scalar_one()
    assert still_there == 1

    # The real owner can remove it.
    own_delete = await client.delete(
        f"/api/v1/push-subscriptions/{subscription_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert own_delete.status_code == 204


async def test_vapid_public_key_reports_configured_when_keys_are_set(client, settings) -> None:  # type: ignore[no-untyped-def]
    resp = await client.get("/api/v1/push/vapid-public-key")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # This dev/test environment has a real generated keypair on file
    # (apps/api/.env) — not a live push-service credential, just proof
    # this endpoint reflects whatever settings.vapid_public_key holds.
    assert body["configured"] is (settings.vapid_public_key != "")
    if body["configured"]:
        assert body["public_key"] == settings.vapid_public_key


def test_send_push_sync_raises_subscription_gone_on_410(monkeypatch, settings) -> None:  # type: ignore[no-untyped-def]
    class _FakeResponse:
        status_code = 410

    def _fake_webpush(**kwargs):  # type: ignore[no-untyped-def]
        raise WebPushException("gone", response=_FakeResponse())

    monkeypatch.setattr(push_service, "webpush", _fake_webpush)
    with pytest.raises(push_service.PushSubscriptionGone):
        push_service.send_push_sync(
            settings,
            endpoint="https://push.example.com/dead",
            p256dh_key="k",
            auth_key="a",
            title="t",
            body="b",
            url=None,
        )


def test_send_push_sync_propagates_other_webpush_errors(monkeypatch, settings) -> None:  # type: ignore[no-untyped-def]
    class _FakeResponse:
        status_code = 500

    def _fake_webpush(**kwargs):  # type: ignore[no-untyped-def]
        raise WebPushException("server error", response=_FakeResponse())

    monkeypatch.setattr(push_service, "webpush", _fake_webpush)
    with pytest.raises(WebPushException):
        push_service.send_push_sync(
            settings,
            endpoint="https://push.example.com/flaky",
            p256dh_key="k",
            auth_key="a",
            title="t",
            body="b",
            url=None,
        )


def test_send_push_sync_succeeds_with_no_exception(monkeypatch, settings) -> None:  # type: ignore[no-untyped-def]
    calls = []

    def _fake_webpush(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)

    monkeypatch.setattr(push_service, "webpush", _fake_webpush)
    push_service.send_push_sync(
        settings,
        endpoint="https://push.example.com/ok",
        p256dh_key="k",
        auth_key="a",
        title="Hello",
        body="World",
        url="/learn",
    )
    assert len(calls) == 1
    assert calls[0]["vapid_claims"] == {"sub": settings.vapid_subject}
    # A nonzero TTL is load-bearing: pywebpush's default of 0 is rejected
    # by WNS (Edge on Windows) with 400 "Ttl value conflicts with
    # X-WNS-Cache-Policy" — found by the live smoke test, not a unit test.
    assert calls[0]["ttl"] == push_service.PUSH_TTL_SECONDS > 0
