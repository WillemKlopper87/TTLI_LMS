"""Phase 5 sprint 2: manager visibility (02 §4.5, REQ-TEN-03, 04 §2.3's
P2 policy). The demo target itself — a manager who cannot see individual
scores until an admin enables it, for one course, and that enabling
requires the course toggle, the tenant toggle, and a real per-organisation
grant (`manager`/`admin` relationship, or the platform-wide RBAC
permission) all at once.
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
    return f"mgrvis-{uuid.uuid4().hex[:12]}@example.com"


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


async def _buy_and_assign_one_seat(
    client,
    admin_token: str,
    finance_token: str,
    *,
    organisation_id: str,
    price_id: str,
    course_id: str,
) -> str:
    """A minimal real seat: PO checkout, finance approval, one employee
    invited. Returns the employee's email."""
    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "registered_business",
            "lines": [{"price_id": price_id, "quantity": 1}],
            "organisation_id": organisation_id,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]

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
        headers={"Authorization": f"Bearer {finance_token}"},
    )
    assert approve.status_code == 200, approve.text

    email = _unique_email()
    invite = await client.post(
        f"/api/v1/organisations/{organisation_id}/seats/invite",
        json={"course_id": course_id, "emails": [email]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invite.status_code == 200, invite.text
    assert invite.json()["items"][0]["ok"] is True
    return email


async def _reset_visibility(client, token: str, course_id: str) -> None:
    """Both toggles are tenant/course-global state shared with every
    other test file that touches the same seeded demo course — always
    put them back, even on assertion failure, so this file can't leak
    into a later one's expectations."""
    await client.patch(
        f"/api/v1/courses/{course_id}/manager-visibility",
        json={"manager_visibility": "aggregate_only"},
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.patch(
        "/api/v1/tenant/settings/manager-visibility",
        json={"allow_manager_individual_results": False},
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_aggregate_only_by_default(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    org_id = await _create_organisation(client, admin_token, "Aggregate Only Co")
    await _buy_and_assign_one_seat(
        client,
        admin_token,
        finance_token,
        organisation_id=org_id,
        price_id=price_id,
        course_id=course_id,
    )

    resp = await client.get(
        f"/api/v1/organisations/{org_id}/reports/progress?course_id={course_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enrolled"] == 1
    assert body["individual_visible"] is False
    assert body["learners"] == []


async def test_individual_visible_once_all_three_conditions_hold(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    org_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    # A platform administrator — distinct from the org's own admin — is
    # who actually holds course:edit/tenant:manage (REQ-TEN-03's "admin
    # enables it").
    platform_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    org_id = await _create_organisation(client, org_admin_token, "Unlocked Co")
    employee_email = await _buy_and_assign_one_seat(
        client,
        org_admin_token,
        finance_token,
        organisation_id=org_id,
        price_id=price_id,
        course_id=course_id,
    )

    try:
        # Condition 1: the course-level toggle.
        course_patch = await client.patch(
            f"/api/v1/courses/{course_id}/manager-visibility",
            json={"manager_visibility": "individual_enabled"},
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )
        assert course_patch.status_code == 200, course_patch.text
        assert course_patch.json()["manager_visibility"] == "individual_enabled"

        # Condition 2: the tenant-level toggle.
        tenant_patch = await client.patch(
            "/api/v1/tenant/settings/manager-visibility",
            json={"allow_manager_individual_results": True},
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )
        assert tenant_patch.status_code == 200, tenant_patch.text
        assert tenant_patch.json()["allow_manager_individual_results"] is True

        # Condition 3: the org admin — already relationship="admin" from
        # creating the organisation — is the viewer.
        resp = await client.get(
            f"/api/v1/organisations/{org_id}/reports/progress?course_id={course_id}",
            headers={"Authorization": f"Bearer {org_admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["individual_visible"] is True
        assert len(body["learners"]) == 1
        assert body["learners"][0]["email"] == employee_email
        assert body["learners"][0]["status"] == "not_started"
    finally:
        await _reset_visibility(client, platform_admin_token, course_id)


async def test_plain_member_never_sees_individual_rows_even_with_both_toggles_on(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    org_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    platform_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    org_id = await _create_organisation(client, org_admin_token, "Member View Co")
    employee_email = await _buy_and_assign_one_seat(
        client,
        org_admin_token,
        finance_token,
        organisation_id=org_id,
        price_id=price_id,
        course_id=course_id,
    )
    await client.patch(
        f"/api/v1/courses/{course_id}/manager-visibility",
        json={"manager_visibility": "individual_enabled"},
        headers={"Authorization": f"Bearer {platform_admin_token}"},
    )
    await client.patch(
        "/api/v1/tenant/settings/manager-visibility",
        json={"allow_manager_individual_results": True},
        headers={"Authorization": f"Bearer {platform_admin_token}"},
    )

    try:
        # The invited employee is a plain "member" of their own
        # organisation (assign_seat's default relationship, find-or-create
        # left them password-less — magic-link-only in reality, same as
        # test_organisations.py's own precedent) — log in as them via a
        # real magic link and view the same report.
        async with tenant_session_factory(tenant_id) as s:
            raw = await identity.create_magic_link(
                s,
                crypto,
                tenant_id=tenant_id,
                email=employee_email,
                minutes=settings.magic_link_minutes,
            )
        consumed = await client.post("/api/v1/auth/magic-link/consume", json={"token": raw})
        assert consumed.status_code == 200, consumed.text
        employee_token = consumed.json()["access_token"]

        resp = await client.get(
            f"/api/v1/organisations/{org_id}/reports/progress?course_id={course_id}",
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["individual_visible"] is False
        assert body["learners"] == []
    finally:
        await _reset_visibility(client, platform_admin_token, course_id)


async def test_missing_tenant_toggle_still_hides_individual_rows(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Course toggle on, tenant toggle left off — aggregate only. Proves
    the two toggles are independent, neither substitutes for the other."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    org_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    platform_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    org_id = await _create_organisation(client, org_admin_token, "Half Unlocked Co")
    await _buy_and_assign_one_seat(
        client,
        org_admin_token,
        finance_token,
        organisation_id=org_id,
        price_id=price_id,
        course_id=course_id,
    )

    try:
        # Explicitly leave the tenant toggle off (default), only flip the course.
        await client.patch(
            f"/api/v1/courses/{course_id}/manager-visibility",
            json={"manager_visibility": "individual_enabled"},
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )
        await client.patch(
            "/api/v1/tenant/settings/manager-visibility",
            json={"allow_manager_individual_results": False},
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )

        resp = await client.get(
            f"/api/v1/organisations/{org_id}/reports/progress?course_id={course_id}",
            headers={"Authorization": f"Bearer {org_admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["individual_visible"] is False
    finally:
        await _reset_visibility(client, platform_admin_token, course_id)


async def test_only_org_members_can_view_the_report(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    course_id = await _demo_course_id(tenant_session_factory)
    org_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    org_id = await _create_organisation(client, org_admin_token, "Private Report Co")

    resp = await client.get(
        f"/api/v1/organisations/{org_id}/reports/progress?course_id={course_id}",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert resp.status_code == 403


async def test_course_and_tenant_toggle_endpoints_round_trip(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    course_id = await _demo_course_id(tenant_session_factory)
    platform_admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    try:
        courses = await client.get(
            "/api/v1/courses", headers={"Authorization": f"Bearer {platform_admin_token}"}
        )
        assert courses.status_code == 200, courses.text
        assert any(c["id"] == course_id for c in courses.json()["items"])

        forbidden_patch = await client.patch(
            f"/api/v1/courses/{course_id}/manager-visibility",
            json={"manager_visibility": "individual_enabled"},
            headers={"Authorization": f"Bearer {learner_token}"},
        )
        assert forbidden_patch.status_code == 403

        patched = await client.patch(
            f"/api/v1/courses/{course_id}/manager-visibility",
            json={"manager_visibility": "individual_enabled"},
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )
        assert patched.status_code == 200, patched.text
        refetched = await client.get(
            "/api/v1/courses", headers={"Authorization": f"Bearer {platform_admin_token}"}
        )
        row = next(c for c in refetched.json()["items"] if c["id"] == course_id)
        assert row["manager_visibility"] == "individual_enabled"

        setting = await client.get(
            "/api/v1/tenant/settings/manager-visibility",
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )
        assert setting.status_code == 200, setting.text
        assert setting.json()["allow_manager_individual_results"] is False

        forbidden_get = await client.get(
            "/api/v1/tenant/settings/manager-visibility",
            headers={"Authorization": f"Bearer {learner_token}"},
        )
        assert forbidden_get.status_code == 403

        await client.patch(
            "/api/v1/tenant/settings/manager-visibility",
            json={"allow_manager_individual_results": True},
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )
        setting_after = await client.get(
            "/api/v1/tenant/settings/manager-visibility",
            headers={"Authorization": f"Bearer {platform_admin_token}"},
        )
        assert setting_after.json()["allow_manager_individual_results"] is True
    finally:
        await _reset_visibility(client, platform_admin_token, course_id)
