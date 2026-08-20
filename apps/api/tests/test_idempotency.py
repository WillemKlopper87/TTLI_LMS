"""`Idempotency-Key` handling (03 §1.6, `core/idempotency.py`): the
middleware itself, isolated from the refund/order business logic
`tests/test_refunds.py`/`tests/test_commerce.py` already cover.

`POST /orders` is used as the scoped endpoint under test throughout —
it's the simplest of the four scoped routes to set up (no prior order
needed) and its side effect (a new `orders` row) is trivial to count,
which is exactly what proves a replay didn't re-execute anything.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import jwt
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
    return f"idem-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        price_id = (
            await s.execute(sa.text("SELECT id FROM prices ORDER BY created_at LIMIT 1"))
        ).scalar_one()
    return str(price_id)


async def _login(client, tenant_session_factory, crypto, *, tenant_id) -> str:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD)
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _user_id_from_token(token: str) -> str:
    # Unverified decode — this is a test reading its own just-issued
    # token's `sub` claim to correlate database rows, not a security
    # boundary, so signature verification would add nothing here.
    return str(jwt.decode(token, options={"verify_signature": False})["sub"])


async def _order_count(tenant_session_factory, tenant_id, user_id: str) -> int:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return (
            await s.execute(
                sa.text("SELECT count(*) FROM orders WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar_one()


async def test_missing_idempotency_key_is_refused(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)

    resp = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_same_key_and_body_replays_the_original_response_without_reexecuting(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The literal spec requirement: same key + same body → the original
    response, not a second execution. Proven two ways — the response
    bodies are identical (same order id) and the database only ever
    gained one row, not two.
    """
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    user_id = _user_id_from_token(token)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)

    body = {
        "currency": "ZAR",
        "customer_type": "individual",
        "lines": [{"price_id": price_id, "quantity": 1}],
    }
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": uuid.uuid4().hex}

    first = await client.post("/api/v1/orders", json=body, headers=headers)
    assert first.status_code == 201, first.text
    before_count = await _order_count(tenant_session_factory, tenant_id, user_id)
    assert before_count == 1

    second = await client.post("/api/v1/orders", json=body, headers=headers)
    assert second.status_code == first.status_code
    assert second.json() == first.json()

    # The decisive check: still exactly one order, not two.
    after_count = await _order_count(tenant_session_factory, tenant_id, user_id)
    assert after_count == 1


async def test_same_key_different_body_is_refused_with_409(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    key = uuid.uuid4().hex
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}

    first = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text

    conflicting = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 2}],
        },
        headers=headers,
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


async def test_different_users_do_not_share_a_key(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Two different buyers who happen to generate the same client-side
    UUID (a real, if rare, possibility — it's still just a string this
    system doesn't control the origin of) must not collide, since a
    collision here would mean one buyer's replay could return another
    buyer's order."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token_a = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    token_b = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    key = uuid.uuid4().hex
    body = {
        "currency": "ZAR",
        "customer_type": "individual",
        "lines": [{"price_id": price_id, "quantity": 1}],
    }

    resp_a = await client.post(
        "/api/v1/orders",
        json=body,
        headers={"Authorization": f"Bearer {token_a}", "Idempotency-Key": key},
    )
    resp_b = await client.post(
        "/api/v1/orders",
        json=body,
        headers={"Authorization": f"Bearer {token_b}", "Idempotency-Key": key},
    )
    assert resp_a.status_code == 201
    assert resp_b.status_code == 201
    assert resp_a.json()["id"] != resp_b.json()["id"]


async def test_unscoped_endpoint_needs_no_idempotency_key(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The middleware's SCOPED_ROUTES allowlist, proven from the outside:
    an endpoint not on the list works with no header at all, same as
    before this feature existed."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


async def test_concurrent_replays_execute_the_handler_exactly_once(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The race the reservation flow (0032) exists for: two identical
    requests in flight at once. Pre-fix, both missed the lookup, both
    created an order, and the loser got a 500 from the unique index after
    its duplicate was already durable. Now the index serialises them at
    the INSERT: exactly one order row, and the loser is either the cached
    replay (it arrived after the winner recorded its response) or an
    honest 409 IDEMPOTENCY_REPLAY_IN_FLIGHT — never a second execution,
    never a 5xx."""
    import asyncio

    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    user_id = _user_id_from_token(token)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)

    body = {
        "currency": "ZAR",
        "customer_type": "individual",
        "lines": [{"price_id": price_id, "quantity": 1}],
    }
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": uuid.uuid4().hex}

    first, second = await asyncio.gather(
        client.post("/api/v1/orders", json=body, headers=headers),
        client.post("/api/v1/orders", json=body, headers=headers),
    )

    statuses = sorted([first.status_code, second.status_code])
    assert statuses[0] == 201, (first.text, second.text)
    assert statuses[1] in (201, 409), (first.text, second.text)
    if statuses[1] == 409:
        loser = first if first.status_code == 409 else second
        assert loser.json()["error"]["code"] == "IDEMPOTENCY_REPLAY_IN_FLIGHT"
    else:
        # Both 201 is only legal as replay-of-the-same-response —
        # identical bodies, identical order id.
        assert first.json() == second.json()

    assert await _order_count(tenant_session_factory, tenant_id, user_id) == 1


async def test_in_flight_reservation_is_released_when_the_attempt_dies(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """A refused attempt below 500 caches; a 5xx (or a crash) must not
    poison the key. Simulated at the storage layer: an in-flight
    reservation row with no response recorded blocks a retry only while
    fresh — the middleware's takeover path reclaims a stale one rather
    than refusing forever."""
    import sqlalchemy as sa

    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)

    body = {
        "currency": "ZAR",
        "customer_type": "individual",
        "lines": [{"price_id": price_id, "quantity": 1}],
    }
    key = uuid.uuid4().hex
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}

    first = await client.post("/api/v1/orders", json=body, headers=headers)
    assert first.status_code == 201, first.text

    # Regress the stored row to a *stale* in-flight reservation — the
    # on-disk state a crash between handler-commit and response-UPDATE
    # leaves behind, five-plus minutes later.
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "UPDATE idempotency_keys"
                " SET response_status = NULL, response_body = NULL,"
                "     created_at = now() - interval '6 minutes'"
                " WHERE idempotency_key = :k"
            ),
            {"k": key},
        )

    retry = await client.post("/api/v1/orders", json=body, headers=headers)
    # The takeover path re-executed the handler (a second order is
    # correct here: the first attempt is presumed dead, this IS the
    # retry) and recorded its response over the reclaimed reservation.
    assert retry.status_code == 201, retry.text
    async with tenant_session_factory(tenant_id) as s:
        recorded = (
            await s.execute(
                sa.text("SELECT response_status FROM idempotency_keys WHERE idempotency_key = :k"),
                {"k": key},
            )
        ).scalar_one()
    assert recorded == 201
