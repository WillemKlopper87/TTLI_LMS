"""Product authoring (frontend backlog item 5): making an authored course
purchasable, and the guards around doing so.

The end-to-end assertion that matters is the last test: author a course,
sell it, buy it through the real EFT path, and land a real enrolment —
proving `Product.course_id` written through the API produces the same
result as the one migration `0009` used to plant by hand.
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
    return f"cat-{uuid.uuid4().hex[:12]}@example.com"


def _unique_slug() -> str:
    return f"prod-{uuid.uuid4().hex[:10]}"


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


async def _author_course(client, token: str, *, assign: bool = True) -> str:
    auth = {"Authorization": f"Bearer {token}"}
    course = await client.post(
        "/api/v1/courses",
        json={"title": f"Catalogue Test Course {uuid.uuid4().hex[:8]}"},
        headers=auth,
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]
    module = await client.post(
        f"/api/v1/courses/{course_id}/modules", json={"title": "Module 1"}, headers=auth
    )
    assert module.status_code == 201, module.text
    lesson = await client.post(
        f"/api/v1/modules/{module.json()['id']}/lessons",
        json={"title": "Lesson 1"},
        headers=auth,
    )
    assert lesson.status_code == 201, lesson.text
    published = await client.post(f"/api/v1/courses/{course_id}/publish", headers=auth)
    assert published.status_code == 200, published.text
    if assign:
        assigned = await client.post(
            f"/api/v1/courses/{course_id}/tenant-assignments",
            json={"is_bespoke": False},
            headers=auth,
        )
        assert assigned.status_code == 201, assigned.text
    return str(course_id)


async def test_product_authoring_requires_product_manage(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The seeded `learner` role must not be able to price anything.

    Logged in as a real role rather than role=None, for the same reason
    test_quiz_list_and_detail_require_course_edit does: "no permissions at
    all fails" proves much less than "a real, populated role still fails".
    """
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    auth = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/catalogue/products", headers=auth)).status_code == 403
    assert (await client.get("/api/v1/catalogue/sellable-courses", headers=auth)).status_code == 403
    created = await client.post(
        "/api/v1/catalogue/products",
        json={"slug": _unique_slug(), "name": "Sneaky"},
        headers=auth,
    )
    assert created.status_code == 403


async def test_content_author_cannot_price_products(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """0022 deliberately withholds `product:manage` from content_author,
    even though 0002 grants it the neighbouring subscription_plan:manage.
    Asserted so the divergence is enforced, not just documented."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    resp = await client.post(
        "/api/v1/catalogue/products",
        json={"slug": _unique_slug(), "name": "Authored but not priced"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_product_cannot_be_published_without_a_price(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    auth = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/api/v1/catalogue/products",
        json={"slug": _unique_slug(), "name": "Priceless"},
        headers=auth,
    )
    assert created.status_code == 201, created.text
    product = created.json()
    # Created inactive on purpose — a live product with nothing to buy is
    # a broken storefront, not an unfinished one.
    assert product["is_active"] is False

    refused = await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=auth
    )
    assert refused.status_code == 400
    assert "price" in refused.json()["error"]["message"].lower()

    priced = await client.post(
        f"/api/v1/catalogue/products/{product['id']}/prices",
        json={"currency": "ZAR", "unit_amount": "1250.00"},
        headers=auth,
    )
    assert priced.status_code == 201, priced.text

    published = await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=auth
    )
    assert published.status_code == 200, published.text
    assert published.json()["is_active"] is True


async def test_cannot_sell_a_course_not_assigned_to_this_tenant(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """`courses` is global, so the tenant boundary lives entirely in
    course_tenant_assignments — without that check a tenant could attach
    (and sell) another tenant's course."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    auth = {"Authorization": f"Bearer {token}"}

    unassigned_course = await _author_course(client, token, assign=False)
    refused = await client.post(
        "/api/v1/catalogue/products",
        json={"slug": _unique_slug(), "name": "Not mine", "course_id": unassigned_course},
        headers=auth,
    )
    assert refused.status_code == 400
    assert "not assigned" in refused.json()["error"]["message"].lower()


async def test_price_used_by_an_order_cannot_be_deleted(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    auth = {"Authorization": f"Bearer {token}"}

    course_id = await _author_course(client, token)
    product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={"slug": _unique_slug(), "name": "Deletable?", "course_id": course_id},
            headers=auth,
        )
    ).json()
    price = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "800.00"},
            headers=auth,
        )
    ).json()

    # Unused: deletes cleanly.
    spare = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "999.00"},
            headers=auth,
        )
    ).json()
    assert (
        await client.delete(f"/api/v1/catalogue/prices/{spare['id']}", headers=auth)
    ).status_code == 204

    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=auth
    )
    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price["id"], "quantity": 1}],
        },
        headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert order.status_code == 201, order.text

    refused = await client.delete(f"/api/v1/catalogue/prices/{price['id']}", headers=auth)
    assert refused.status_code == 400
    assert "order" in refused.json()["error"]["message"].lower()


async def test_authored_course_can_be_sold_and_bought_end_to_end(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The whole point of item 5: a course authored through the API can be
    made purchasable and actually bought, producing a real enrolment.

    Before this, `Product.course_id` could only be written by a migration,
    so nothing but the seeded demo product was ever buyable.
    """
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    admin_auth = {"Authorization": f"Bearer {admin}"}

    course_id = await _author_course(client, admin)

    # It shows up as sellable, and as not yet sold.
    sellable = await client.get("/api/v1/catalogue/sellable-courses", headers=admin_auth)
    assert sellable.status_code == 200, sellable.text
    row = next(c for c in sellable.json()["items"] if c["id"] == course_id)
    assert row["already_sold_as"] is None

    product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": _unique_slug(),
                "name": "Newly Authored Programme",
                "description": "Sold through the API, not a migration.",
                "course_id": course_id,
            },
            headers=admin_auth,
        )
    ).json()
    price = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "1500.00"},
            headers=admin_auth,
        )
    ).json()
    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=admin_auth
    )

    # Now it's in the public storefront, which is unauthenticated.
    public = await client.get("/api/v1/products")
    assert public.status_code == 200
    assert any(p["id"] == product["id"] for p in public.json()["items"])

    # And the sellable list now reports it as already sold.
    resold = await client.get("/api/v1/catalogue/sellable-courses", headers=admin_auth)
    assert (
        next(c for c in resold.json()["items"] if c["id"] == course_id)["already_sold_as"]
        == "Newly Authored Programme"
    )

    # A real buyer purchases it through the real EFT path.
    buyer_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    buyer_auth = {"Authorization": f"Bearer {buyer_token}"}

    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price["id"], "quantity": 1}],
        },
        headers={**buyer_auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]

    checkout = await client.post(f"/api/v1/orders/{order_id}/checkout/eft", headers=buyer_auth)
    assert checkout.status_code == 200, checkout.text
    # Take the payment id from the checkout response rather than paging
    # GET /payments for it, exactly as test_commerce.py does: the queue is
    # paginated and a long-lived dev database has a deep backlog of
    # unrelated pending orders, so scanning page one for this order is a
    # coin flip that has nothing to do with what's under test.
    payment_id = checkout.json()["payment_id"]

    proof = await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
        headers=buyer_auth,
    )
    # 204: the upload is scanned by the real ClamAV and stored, with no body.
    assert proof.status_code == 204, proof.text

    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    approved = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approved.status_code == 200, approved.text

    # The buyer is now genuinely enrolled in the course that was authored
    # at the top of this test — the bridge worked end to end.
    enrolments = await client.get("/api/v1/enrolments", headers=buyer_auth)
    assert enrolments.status_code == 200, enrolments.text
    assert any(e["course_id"] == course_id for e in enrolments.json())
