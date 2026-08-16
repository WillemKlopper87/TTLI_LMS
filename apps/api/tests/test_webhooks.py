"""`POST /webhooks/payfast` (03 §5.7) — the router's own orchestration:
tenant resolution with no `X-Tenant-Host`, signature-then-confirmation
ordering, idempotency on `provider_event_id`, amount verification, and
real fulfilment (a real entitlement, a real ledger pair) on success.

`confirm_with_provider` — the one live round-trip to Payfast's own
servers — is the single piece substituted here, via FastAPI's
`dependency_overrides` on a subclass that keeps every other method real
(signature generation/verification, checkout-field construction, webhook
parsing all run the actual `PayfastProvider` code). This is the same
"substitute only the boundary with no real account to test against"
reasoning `tests/test_storage.py` already uses moto for — not a general
mocking pattern, a narrow one.

The `Payment` row each test needs is created by calling
`services/orders.py::checkout_card` directly rather than through
`POST /orders/{id}/checkout/card` — that HTTP path resolves its provider
from the real, session-wide `Settings` object (always unconfigured, since
no live Payfast account exists), and mutating shared test-session
settings to fake it would leak into every other test file. Calling the
service function directly with a locally-built `_ScriptedProvider`
exercises the exact same `checkout_card` code with no such risk.
"""

from __future__ import annotations

import hashlib
import urllib.parse
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.deps import get_payment_provider
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.models.commerce import Order
from src.models.rbac import RoleAssignment
from src.services import identity
from src.services import orders as orders_service
from src.services.payments.payfast import PayfastProvider

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"
PASSWORD = "correct horse battery staple 9!"
TEST_PASSPHRASE = "jt7NOE43FZPn"


class _ScriptedProvider(PayfastProvider):
    """The real adapter, with only the live network round-trip swapped
    for a value this test controls."""

    def __init__(self, *, confirmed: bool) -> None:
        super().__init__(
            merchant_id="10000100",
            merchant_key="46f0cd694581a",
            passphrase=TEST_PASSPHRASE,
            sandbox=True,
        )
        self._confirmed = confirmed

    async def confirm_with_provider(self, fields: object) -> bool:  # type: ignore[override]
        return self._confirmed


def _redis_reachable(url: str) -> bool:
    import socket
    from urllib.parse import urlparse

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
async def app_and_client(settings, database_url):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip(
            "no Redis on the configured REDIS_URL — run: "
            "docker compose -f infra/docker-compose.yml up -d redis"
        )
    init_engine(settings)
    redis = init_redis(settings)
    await redis.flushdb()
    await init_queue(settings)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.headers["X-Tenant-Host"] = TENANT_HOST
        yield app, c
    app.dependency_overrides.clear()
    await dispose_engine()
    await dispose_redis()
    await dispose_queue()


def _unique_email() -> str:
    return f"webhook-{uuid.uuid4().hex[:12]}@example.com"


def _unique_slug() -> str:
    return f"webhook-prod-{uuid.uuid4().hex[:10]}"


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _login(client, tenant_session_factory, crypto, *, tenant_id, role: str | None) -> str:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role))
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _sellable_course_and_price(client, admin_token: str) -> tuple[str, str, str]:
    auth = {"Authorization": f"Bearer {admin_token}"}
    course = await client.post(
        "/api/v1/courses",
        json={"title": f"Webhook Test Course {uuid.uuid4().hex[:8]}"},
        headers=auth,
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]
    module = await client.post(
        f"/api/v1/courses/{course_id}/modules", json={"title": "Module 1"}, headers=auth
    )
    lesson = await client.post(
        f"/api/v1/modules/{module.json()['id']}/lessons", json={"title": "Lesson 1"}, headers=auth
    )
    assert lesson.status_code == 201, lesson.text
    lesson_id = lesson.json()["id"]
    assert (
        await client.post(f"/api/v1/courses/{course_id}/publish", headers=auth)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/courses/{course_id}/tenant-assignments",
            json={"is_bespoke": False},
            headers=auth,
        )
    ).status_code == 201

    product = await client.post(
        "/api/v1/catalogue/products",
        json={"slug": _unique_slug(), "name": "Card Checkout Course", "course_id": course_id},
        headers=auth,
    )
    assert product.status_code == 201, product.text
    price = await client.post(
        f"/api/v1/catalogue/products/{product.json()['id']}/prices",
        json={"currency": "ZAR", "unit_amount": "500.00"},
        headers=auth,
    )
    assert price.status_code == 201, price.text
    await client.patch(
        f"/api/v1/catalogue/products/{product.json()['id']}",
        json={"is_active": True},
        headers=auth,
    )
    return course_id, lesson_id, str(price.json()["id"])


async def _create_pending_order(client, buyer_token: str, price_id: str) -> str:
    resp = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {buyer_token}", **_idem()},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _card_checkout(
    tenant_session_factory, crypto, *, tenant_id, order_id: str, provider: PayfastProvider
) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        order = await s.get(Order, uuid.UUID(order_id))
        assert order is not None
        payment, _redirect = await orders_service.checkout_card(
            s,
            crypto,
            tenant_id=tenant_id,
            order=order,
            provider=provider,
            return_url="https://example.com/return",
            cancel_url="https://example.com/cancel",
            notify_url="https://example.com/notify",
        )
        return payment.id


def _sign(fields: dict[str, str]) -> dict[str, str]:
    """Builds a synthetic-but-genuinely-valid ITN — signed the exact way
    `PayfastProvider.verify_signature` will check it, so these tests
    exercise the real algorithm rather than a stand-in for it."""
    query = "&".join(f"{k}={urllib.parse.quote_plus(v)}" for k, v in fields.items())
    query += f"&passphrase={urllib.parse.quote_plus(TEST_PASSPHRASE)}"
    signed = dict(fields)
    signed["signature"] = hashlib.md5(query.encode()).hexdigest()  # noqa: S324
    return signed


async def test_invalid_signature_is_refused_and_audited(  # type: ignore[no-untyped-def]
    app_and_client, tenant_session_factory, crypto
) -> None:
    app, client = app_and_client
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    _, _, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _create_pending_order(client, buyer_token, price_id)

    provider = _ScriptedProvider(confirmed=True)
    payment_id = await _card_checkout(
        tenant_session_factory, crypto, tenant_id=tenant_id, order_id=order_id, provider=provider
    )

    tampered = {
        "m_payment_id": str(payment_id),
        "pf_payment_id": f"reject-{uuid.uuid4().hex[:10]}",
        "payment_status": "COMPLETE",
        "amount_gross": "575.00",
        "signature": "0" * 32,  # well-formed but wrong
    }

    app.dependency_overrides[get_payment_provider] = lambda: provider
    resp = await client.post("/api/v1/webhooks/payfast", data=tampered)
    assert resp.status_code == 401

    async with tenant_session_factory(tenant_id) as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT id FROM audit_events WHERE entity_id = :p "
                    "AND action = 'payment.webhook.rejected'"
                ),
                {"p": str(payment_id)},
            )
        ).all()
    assert len(rows) == 1


async def test_confirmation_failure_is_refused_and_audited(  # type: ignore[no-untyped-def]
    app_and_client, tenant_session_factory, crypto
) -> None:
    """A validly-*signed* notification the live provider round-trip
    doesn't confirm — the second, independent anti-forgery layer Payfast
    itself documents alongside signature checking."""
    app, client = app_and_client
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    _, _, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _create_pending_order(client, buyer_token, price_id)

    provider = _ScriptedProvider(confirmed=False)
    payment_id = await _card_checkout(
        tenant_session_factory, crypto, tenant_id=tenant_id, order_id=order_id, provider=provider
    )

    signed = _sign(
        {
            "m_payment_id": str(payment_id),
            "pf_payment_id": f"unconfirmed-{uuid.uuid4().hex[:10]}",
            "payment_status": "COMPLETE",
            "amount_gross": "575.00",
        }
    )

    app.dependency_overrides[get_payment_provider] = lambda: provider
    resp = await client.post("/api/v1/webhooks/payfast", data=signed)
    assert resp.status_code == 401

    async with tenant_session_factory(tenant_id) as s:
        order_status = (
            await s.execute(sa.text("SELECT status FROM orders WHERE id = :o"), {"o": order_id})
        ).scalar_one()
    assert order_status == "pending_payment"


async def test_successful_notification_fulfils_the_order(  # type: ignore[no-untyped-def]
    app_and_client, tenant_session_factory, crypto
) -> None:
    app, client = app_and_client
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    _, lesson_id, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _create_pending_order(client, buyer_token, price_id)

    provider = _ScriptedProvider(confirmed=True)
    payment_id = await _card_checkout(
        tenant_session_factory, crypto, tenant_id=tenant_id, order_id=order_id, provider=provider
    )

    signed = _sign(
        {
            "m_payment_id": str(payment_id),
            "pf_payment_id": f"success-{uuid.uuid4().hex[:10]}",
            "payment_status": "COMPLETE",
            "amount_gross": "575.00",
        }
    )

    app.dependency_overrides[get_payment_provider] = lambda: provider
    resp = await client.post("/api/v1/webhooks/payfast", data=signed)
    assert resp.status_code == 200

    async with tenant_session_factory(tenant_id) as s:
        order_row = (
            await s.execute(sa.text("SELECT status FROM orders WHERE id = :o"), {"o": order_id})
        ).first()
        assert order_row is not None and order_row.status == "fulfilled"

        payment_row = (
            await s.execute(
                sa.text("SELECT status, approved_by_user_id FROM payments WHERE id = :p"),
                {"p": str(payment_id)},
            )
        ).first()
        assert payment_row is not None
        assert payment_row.status == "complete"
        assert payment_row.approved_by_user_id is None  # a gateway confirmed it, not a human

        ledger_types = (
            (
                await s.execute(
                    sa.text(
                        "SELECT entry_type FROM ledger_entries WHERE entity_type = 'payment' "
                        "AND entity_id = :p"
                    ),
                    {"p": str(payment_id)},
                )
            )
            .scalars()
            .all()
        )
        assert "payment_received" in ledger_types

        webhook_row = (
            await s.execute(
                sa.text(
                    "SELECT id FROM payment_webhooks WHERE provider = 'payfast' AND payment_id = :p"
                ),
                {"p": str(payment_id)},
            )
        ).first()
        assert webhook_row is not None

    # Real access, not just database state — the same gate a lapsed
    # subscription is checked against (services/enrolment.py::
    # get_own_enrolment).
    started = await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert started.status_code == 204, started.text


async def test_replayed_notification_does_not_reprocess(  # type: ignore[no-untyped-def]
    app_and_client, tenant_session_factory, crypto
) -> None:
    app, client = app_and_client
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    _, _, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _create_pending_order(client, buyer_token, price_id)

    provider = _ScriptedProvider(confirmed=True)
    payment_id = await _card_checkout(
        tenant_session_factory, crypto, tenant_id=tenant_id, order_id=order_id, provider=provider
    )

    event_id = f"replay-{uuid.uuid4().hex[:10]}"
    signed = _sign(
        {
            "m_payment_id": str(payment_id),
            "pf_payment_id": event_id,
            "payment_status": "COMPLETE",
            "amount_gross": "575.00",
        }
    )

    app.dependency_overrides[get_payment_provider] = lambda: provider
    first = await client.post("/api/v1/webhooks/payfast", data=signed)
    assert first.status_code == 200
    second = await client.post("/api/v1/webhooks/payfast", data=signed)
    assert second.status_code == 200

    async with tenant_session_factory(tenant_id) as s:
        webhook_count = (
            await s.execute(
                sa.text(
                    "SELECT count(*) FROM payment_webhooks WHERE provider = 'payfast' "
                    "AND provider_event_id = :e"
                ),
                {"e": event_id},
            )
        ).scalar_one()
        ledger_count = (
            await s.execute(
                sa.text(
                    "SELECT count(*) FROM ledger_entries WHERE entity_type = 'payment' "
                    "AND entity_id = :p AND entry_type = 'payment_received'"
                ),
                {"p": str(payment_id)},
            )
        ).scalar_one()
    assert webhook_count == 1
    assert ledger_count == 1


async def test_amount_mismatch_is_not_fulfilled(  # type: ignore[no-untyped-def]
    app_and_client, tenant_session_factory, crypto
) -> None:
    app, client = app_and_client
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    _, _, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _create_pending_order(client, buyer_token, price_id)

    provider = _ScriptedProvider(confirmed=True)
    payment_id = await _card_checkout(
        tenant_session_factory, crypto, tenant_id=tenant_id, order_id=order_id, provider=provider
    )

    # The order is really 575.00 (500 + 15% VAT) — this claims far less,
    # simulating a tampered or simply wrong amount_gross.
    signed = _sign(
        {
            "m_payment_id": str(payment_id),
            "pf_payment_id": f"mismatch-{uuid.uuid4().hex[:10]}",
            "payment_status": "COMPLETE",
            "amount_gross": "1.00",
        }
    )

    app.dependency_overrides[get_payment_provider] = lambda: provider
    resp = await client.post("/api/v1/webhooks/payfast", data=signed)
    assert resp.status_code == 200  # signature/source were genuine — just a data anomaly

    async with tenant_session_factory(tenant_id) as s:
        order_row = (
            await s.execute(sa.text("SELECT status FROM orders WHERE id = :o"), {"o": order_id})
        ).first()
        assert order_row is not None and order_row.status == "pending_payment"


async def test_unresolvable_payment_id_is_a_no_op(app_and_client) -> None:  # type: ignore[no-untyped-def]
    """No tenant can be resolved for a payment id that doesn't exist —
    nothing to sign against, nothing to be suspicious about under any
    tenant in particular, just an unrecognised notification."""
    _app, client = app_and_client
    resp = await client.post(
        "/api/v1/webhooks/payfast",
        data={
            "m_payment_id": str(uuid.uuid4()),
            "pf_payment_id": f"ghost-{uuid.uuid4().hex[:10]}",
            "payment_status": "COMPLETE",
            "amount_gross": "1.00",
            "signature": "0" * 32,
        },
    )
    assert resp.status_code == 200
