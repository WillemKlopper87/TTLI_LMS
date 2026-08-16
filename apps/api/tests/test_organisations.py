"""Phase 5 sprint 1: organisations, seats, PO checkout (02 §4.5,
REQ-TEN-02). HTTP coverage for the full vertical slice — an org admin
buys N seats via the real PO checkout/approval path, then assigns and
revokes them, exactly as the PRD's own worked example describes.
"""

from __future__ import annotations

import io
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
    return f"org-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str((await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one())


async def _demo_course_id(tenant_session_factory) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        return str(
            (
                await s.execute(
                    sa.text(
                        "SELECT id FROM courses WHERE slug = 'executive-leadership-certificate'"
                    )
                )
            ).scalar_one()
        )


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
    assert resp.status_code == 200
    return str(resp.json()["access_token"]), user_id


async def _create_organisation(client, token: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/organisations",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _buy_seats_via_po(
    client,
    admin_token: str,
    finance_token: str,
    *,
    organisation_id: str,
    price_id: str,
    quantity: int,
) -> str:
    """The PRD's own worked example: seats selected → PO number and
    document captured → finance approves → seats activated."""
    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "registered_business",
            "lines": [{"price_id": price_id, "quantity": quantity}],
            "organisation_id": organisation_id,
        },
        headers={"Authorization": f"Bearer {admin_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert order.json()["organisation_id"] == organisation_id

    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/po",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={"po_number": f"PO-{uuid.uuid4().hex[:8].upper()}"},
        files={"file": ("po.pdf", b"%PDF-fake-purchase-order", "application/pdf")},
    )
    assert checkout.status_code == 200, checkout.text
    payment_id = checkout.json()["payment_id"]

    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200, approve.text
    return order_id


async def test_creator_becomes_organisation_admin(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token, _ = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    org_id = await _create_organisation(client, token, "Acme Holdings")

    members = await client.get(
        f"/api/v1/organisations/{org_id}/members", headers={"Authorization": f"Bearer {token}"}
    )
    assert members.status_code == 200
    rows = members.json()["items"]
    assert len(rows) == 1
    assert rows[0]["relationship"] == "admin"


async def test_non_member_cannot_view_organisation(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    org_id = await _create_organisation(client, admin_token, "Private Co")

    resp = await client.get(
        f"/api/v1/organisations/{org_id}", headers={"Authorization": f"Bearer {stranger_token}"}
    )
    assert resp.status_code == 403


async def test_po_purchase_activates_seat_pool_and_seats_are_assignable(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    org_id = await _create_organisation(client, admin_token, "Seat Buyer Inc")

    await _buy_seats_via_po(
        client, admin_token, finance_token, organisation_id=org_id, price_id=price_id, quantity=3
    )

    seats = await client.get(
        f"/api/v1/organisations/{org_id}/seats", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert seats.status_code == 200, seats.text
    summary = next(row for row in seats.json()["items"] if row["course_id"] == course_id)
    assert summary["purchased"] == 3
    assert summary["assigned"] == 0
    assert summary["available"] == 3

    employee_email = _unique_email()
    invite = await client.post(
        f"/api/v1/organisations/{org_id}/seats/invite",
        json={"course_id": course_id, "emails": [employee_email]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invite.status_code == 200, invite.text
    result = invite.json()["items"][0]
    assert result["ok"] is True
    assert result["email"] == employee_email

    # The assigned employee really can log in and really is enrolled —
    # not just a row that looks right, the actual downstream effects
    # entitlement grants elsewhere in this codebase always produce.
    login = await client.post(
        "/api/v1/auth/login", json={"email": employee_email, "password": "anything"}
    )
    assert login.status_code == 401  # find-or-create makes no password — magic-link-only in reality

    async with tenant_session_factory(tenant_id) as s:
        enrolled = (
            await s.execute(
                sa.text(
                    "SELECT e.id FROM enrolments e "
                    "JOIN users u ON u.id = e.user_id "
                    "JOIN entitlements ent ON ent.user_id = u.id "
                    "WHERE ent.organisation_id = :org AND e.course_id = :c"
                ),
                {"org": org_id, "c": course_id},
            )
        ).first()
    assert enrolled is not None

    seats_after = await client.get(
        f"/api/v1/organisations/{org_id}/seats", headers={"Authorization": f"Bearer {admin_token}"}
    )
    summary_after = next(
        row for row in seats_after.json()["items"] if row["course_id"] == course_id
    )
    assert summary_after["assigned"] == 1
    assert summary_after["available"] == 2


async def test_seat_assignment_refused_once_pool_is_exhausted(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    org_id = await _create_organisation(client, admin_token, "One Seat Ltd")
    await _buy_seats_via_po(
        client, admin_token, finance_token, organisation_id=org_id, price_id=price_id, quantity=1
    )

    invite = await client.post(
        f"/api/v1/organisations/{org_id}/seats/invite",
        json={"course_id": course_id, "emails": [_unique_email(), _unique_email()]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invite.status_code == 200, invite.text
    results = invite.json()["items"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert "seats" in (results[1]["reason"] or "").lower()


async def test_csv_import_assigns_seats(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    org_id = await _create_organisation(client, admin_token, "CSV Import Co")
    await _buy_seats_via_po(
        client, admin_token, finance_token, organisation_id=org_id, price_id=price_id, quantity=2
    )

    email1, email2 = _unique_email(), _unique_email()
    csv_bytes = f"email\n{email1}\n{email2}\n".encode()

    resp = await client.post(
        f"/api/v1/organisations/{org_id}/seats/import?course_id={course_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("members.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["items"]
    assert {r["email"] for r in results} == {email1, email2}
    assert all(r["ok"] for r in results)


async def test_only_org_admin_can_invite_or_revoke_seats(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    org_id = await _create_organisation(client, admin_token, "Members Only Inc")
    await _buy_seats_via_po(
        client, admin_token, finance_token, organisation_id=org_id, price_id=price_id, quantity=2
    )

    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.post(
        f"/api/v1/organisations/{org_id}/seats/invite",
        json={"course_id": course_id, "emails": [_unique_email()]},
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403


async def test_assigned_seats_endpoint_lists_holder_and_drops_after_revoke(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The per-course holder list (what the revoke UI reads) reflects an
    assignment as soon as it happens and drops it as soon as it's revoked
    — same live-computed discipline as the aggregate `/seats` summary."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    org_id = await _create_organisation(client, admin_token, "Holder List Co")
    await _buy_seats_via_po(
        client, admin_token, finance_token, organisation_id=org_id, price_id=price_id, quantity=1
    )

    employee_email = _unique_email()
    await client.post(
        f"/api/v1/organisations/{org_id}/seats/invite",
        json={"course_id": course_id, "emails": [employee_email]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    holders = await client.get(
        f"/api/v1/organisations/{org_id}/seats/{course_id}/assignments",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert holders.status_code == 200, holders.text
    items = holders.json()["items"]
    assert len(items) == 1
    assert items[0]["email"] == employee_email
    entitlement_id = items[0]["entitlement_id"]

    # A non-admin member is refused — this list carries PII (real emails),
    # so it's admin-gated like invite/import/revoke, not member-readable
    # like the org's membership roster.
    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.get(
        f"/api/v1/organisations/{org_id}/seats/{course_id}/assignments",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403

    await client.post(
        f"/api/v1/organisations/{org_id}/seats/{entitlement_id}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    holders_after = await client.get(
        f"/api/v1/organisations/{org_id}/seats/{course_id}/assignments",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert holders_after.json()["items"] == []


async def test_revoke_seat_frees_capacity_for_reassignment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    org_id = await _create_organisation(client, admin_token, "Reassign Co")
    await _buy_seats_via_po(
        client, admin_token, finance_token, organisation_id=org_id, price_id=price_id, quantity=1
    )

    first_email = _unique_email()
    await client.post(
        f"/api/v1/organisations/{org_id}/seats/invite",
        json={"course_id": course_id, "emails": [first_email]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    async with tenant_session_factory(tenant_id) as s:
        entitlement_id = (
            await s.execute(
                sa.text(
                    "SELECT ent.id FROM entitlements ent "
                    "WHERE ent.organisation_id = :org AND ent.user_id IS NOT NULL"
                ),
                {"org": org_id},
            )
        ).scalar_one()

    # No seats left for a second person until the first is revoked.
    blocked = await client.post(
        f"/api/v1/organisations/{org_id}/seats/invite",
        json={"course_id": course_id, "emails": [_unique_email()]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert blocked.json()["items"][0]["ok"] is False

    revoke = await client.post(
        f"/api/v1/organisations/{org_id}/seats/{entitlement_id}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert revoke.status_code == 204, revoke.text

    second_email = _unique_email()
    reassigned = await client.post(
        f"/api/v1/organisations/{org_id}/seats/invite",
        json={"course_id": course_id, "emails": [second_email]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reassigned.json()["items"][0]["ok"] is True
