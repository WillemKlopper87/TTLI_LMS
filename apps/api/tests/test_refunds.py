"""Refunds and credit notes (02 §6.3/6.4, Phase 3 remainder): the guards
around who can refund what, and the real end-to-end effect of one — the
invoice credited, the entitlement revoked, both ledger entries written.

Every mutating call in this file needs an `Idempotency-Key` header
(`core/idempotency.py`'s middleware enforces it on exactly these routes);
`tests/test_idempotency.py` covers the replay/conflict semantics
themselves, this file just supplies a fresh key per call so the business
logic under test is never masked by a cached replay.
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
    return f"refund-{uuid.uuid4().hex[:12]}@example.com"


def _unique_slug() -> str:
    return f"refund-prod-{uuid.uuid4().hex[:10]}"


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _login(
    client, tenant_session_factory, crypto, *, tenant_id, role: str | None
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
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


async def _sellable_course_and_price(client, admin_token: str) -> tuple[str, str, str]:
    """A fresh, real course → product → price, built through the actual
    authoring APIs (frontend backlog item 5), not a raw INSERT — this
    file's whole point is exercising the real refund path end to end."""
    auth = {"Authorization": f"Bearer {admin_token}"}
    course = await client.post(
        "/api/v1/courses",
        json={"title": f"Refund Test Course {uuid.uuid4().hex[:8]}"},
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
        json={"slug": _unique_slug(), "name": "Refundable Course", "course_id": course_id},
        headers=auth,
    )
    assert product.status_code == 201, product.text
    price = await client.post(
        f"/api/v1/catalogue/products/{product.json()['id']}/prices",
        json={"currency": "ZAR", "unit_amount": "900.00"},
        headers=auth,
    )
    assert price.status_code == 201, price.text
    await client.patch(
        f"/api/v1/catalogue/products/{product.json()['id']}",
        json={"is_active": True},
        headers=auth,
    )
    return course_id, lesson_id, str(price.json()["id"])


async def _buy_and_fulfil(client, *, price_id: str, buyer_token: str, finance_token: str) -> str:
    """A real EFT purchase all the way through finance approval. Returns
    the order id, now `fulfilled`, exactly the state `process_refund`
    requires."""
    buyer_auth = {"Authorization": f"Bearer {buyer_token}"}
    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={**buyer_auth, **_idem()},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]

    checkout = await client.post(f"/api/v1/orders/{order_id}/checkout/eft", headers=buyer_auth)
    assert checkout.status_code == 200, checkout.text
    payment_id = checkout.json()["payment_id"]

    proof = await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
        headers=buyer_auth,
    )
    assert proof.status_code == 204, proof.text

    approved = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", **_idem()},
    )
    assert approved.status_code == 200, approved.text
    return order_id


async def test_refund_requires_refund_process_permission(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The seeded `learner` role must not be able to refund its own
    purchase — refund:process is a finance action, checked against a real
    populated role, not just role=None, matching every other permission
    test in this codebase."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    _, _, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _buy_and_fulfil(
        client, price_id=price_id, buyer_token=buyer_token, finance_token=finance_token
    )

    refused = await client.post(
        f"/api/v1/orders/{order_id}/refund",
        json={"reason": "I changed my mind"},
        headers={"Authorization": f"Bearer {buyer_token}", **_idem()},
    )
    assert refused.status_code == 403


async def test_cannot_refund_an_order_that_was_never_fulfilled(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    _, _, price_id = await _sellable_course_and_price(client, admin_token)

    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {buyer_token}", **_idem()},
    )
    order_id = order.json()["id"]

    refused = await client.post(
        f"/api/v1/orders/{order_id}/refund",
        json={"reason": "too early"},
        headers={"Authorization": f"Bearer {finance_token}", **_idem()},
    )
    assert refused.status_code == 400
    assert "not fulfilled" in refused.json()["error"]["message"].lower()


async def test_refund_credits_invoice_revokes_access_and_writes_ledger(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token, buyer_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    course_id, lesson_id, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _buy_and_fulfil(
        client, price_id=price_id, buyer_token=buyer_token, finance_token=finance_token
    )

    # Access exists before the refund.
    enrolments = await client.get(
        "/api/v1/enrolments", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert any(e["course_id"] == course_id for e in enrolments.json())

    refund = await client.post(
        f"/api/v1/orders/{order_id}/refund",
        json={"reason": "duplicate purchase"},
        headers={"Authorization": f"Bearer {finance_token}", **_idem()},
    )
    assert refund.status_code == 200, refund.text
    body = refund.json()
    assert body["order_id"] == order_id
    # The price was seeded at 900.00 excl. tax; South African domestic VAT
    # (15%, services/tax.py) is added server-side, so the order — and
    # therefore the full refund of it — is 900 * 1.15 = 1035.00, not the
    # bare price. Asserted against the real invoice total below too, not
    # just this one hardcoded figure.
    assert body["amount"] == "1035.00"
    assert body["credit_note_number"].startswith("CN-")

    async with tenant_session_factory(tenant_id) as s:
        order_status = (
            await s.execute(sa.text("SELECT status FROM orders WHERE id = :o"), {"o": order_id})
        ).scalar_one()
        assert order_status == "refunded"

        invoice_row = (
            await s.execute(
                sa.text("SELECT status, grand_total FROM invoices WHERE order_id = :o"),
                {"o": order_id},
            )
        ).first()
        assert invoice_row is not None
        assert invoice_row.status == "credited"
        assert str(invoice_row.grand_total) == "1035.00"

        entitlement_row = (
            await s.execute(
                sa.text(
                    "SELECT revoked_at FROM entitlements WHERE source_order_id = :o "
                    "AND user_id = :u"
                ),
                {"o": order_id, "u": str(buyer_id)},
            )
        ).first()
        assert entitlement_row is not None
        assert entitlement_row.revoked_at is not None

        ledger_types = (
            (
                await s.execute(
                    sa.text(
                        "SELECT entry_type FROM ledger_entries WHERE reference LIKE 'CN-%' "
                        "OR entity_type = 'refund'"
                    )
                )
            )
            .scalars()
            .all()
        )
        # Both financial events this refund is required to write, not one
        # standing in for the other — see refunds.py's own module docstring.
        assert "credit_note_issued" in ledger_types
        assert "refund_issued" in ledger_types

    # Access is gone after the refund — checked against POST
    # /lessons/{id}/start, not GET .../progress: get_progress only looks
    # up the Enrolment row (services/enrolment.py::
    # _get_own_enrolment_by_id) and never calls
    # has_valid_course_entitlement, so it would stay 200 refund or not and
    # prove nothing. start_lesson goes through get_own_enrolment, which
    # does check it — the same function a lapsed subscription already
    # relies on to cut off access (services/subscriptions.py) — so this is
    # the actual gate a refund needs to close, verified through the real
    # endpoint rather than assumed from the database row alone.
    blocked = await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert blocked.status_code == 403
    assert "expired" in blocked.json()["error"]["message"].lower()


async def test_refunding_an_already_refunded_order_is_refused(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    _, _, price_id = await _sellable_course_and_price(client, admin_token)
    order_id = await _buy_and_fulfil(
        client, price_id=price_id, buyer_token=buyer_token, finance_token=finance_token
    )

    first = await client.post(
        f"/api/v1/orders/{order_id}/refund",
        json={"reason": "first"},
        headers={"Authorization": f"Bearer {finance_token}", **_idem()},
    )
    assert first.status_code == 200, first.text

    # A different Idempotency-Key: this must reach the real business
    # logic, not just replay the first response, to prove the refusal is
    # a genuine state check and not idempotency doing the work for it.
    second = await client.post(
        f"/api/v1/orders/{order_id}/refund",
        json={"reason": "second"},
        headers={"Authorization": f"Bearer {finance_token}", **_idem()},
    )
    assert second.status_code == 400
    assert "not fulfilled" in second.json()["error"]["message"].lower()
