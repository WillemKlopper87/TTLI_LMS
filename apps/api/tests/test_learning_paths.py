"""Learning-path authoring (`docs/BACKLOG.md` P5): creating a path,
ordering its member courses, the publish blockers, and tenant
assignment. Fixture shape mirrors `test_catalogue.py` closely — same
`client`/`_demo_tenant_id`/`_login` fixtures, same "log in as a real
seeded role" reasoning for the RBAC tests.
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
    return f"path-{uuid.uuid4().hex[:12]}@example.com"


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


async def _published_course(client, auth: dict[str, str]) -> str:
    course = await client.post(
        "/api/v1/courses",
        json={"title": f"Path Member Course {uuid.uuid4().hex[:8]}"},
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
    return str(course_id)


async def test_learning_path_crud_requires_course_edit(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    resp = await client.post(
        "/api/v1/learning-paths",
        json={"title": "Sneaky Path"},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403

    author_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    auth = {"Authorization": f"Bearer {author_token}"}
    created = await client.post(
        "/api/v1/learning-paths", json={"title": "Leadership Fundamentals"}, headers=auth
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["state"] == "draft"
    assert body["slug"]

    fetched = await client.get(f"/api/v1/learning-paths/{body['id']}", headers=auth)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Leadership Fundamentals"

    updated = await client.patch(
        f"/api/v1/learning-paths/{body['id']}",
        json={"description": "Three courses, one credential."},
        headers=auth,
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Three courses, one credential."


async def test_publish_refuses_below_minimum_courses_and_unpublished_members(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    auth = {"Authorization": f"Bearer {token}"}

    path = (
        await client.post("/api/v1/learning-paths", json={"title": "Two Course Path"}, headers=auth)
    ).json()
    path_id = path["id"]

    # Zero courses: refused.
    refused = await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=auth)
    assert refused.status_code == 400, refused.text

    # One published course: still below the minimum.
    course_a = await _published_course(client, auth)
    added = await client.post(
        f"/api/v1/learning-paths/{path_id}/courses", json={"course_id": course_a}, headers=auth
    )
    assert added.status_code == 201, added.text
    still_refused = await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=auth)
    assert still_refused.status_code == 400

    # An unpublished second course: refused for a different reason (draft member).
    draft_course = await client.post(
        "/api/v1/courses", json={"title": f"Draft Member {uuid.uuid4().hex[:8]}"}, headers=auth
    )
    assert draft_course.status_code == 201
    draft_id = draft_course.json()["id"]
    await client.post(
        f"/api/v1/learning-paths/{path_id}/courses", json={"course_id": draft_id}, headers=auth
    )
    readiness = await client.get(f"/api/v1/learning-paths/{path_id}/readiness", headers=auth)
    assert readiness.status_code == 200
    checks = {c["code"]: c for c in readiness.json()["checks"]}
    assert checks["has_courses"]["ok"] is True
    assert checks["member_courses_published"]["ok"] is False
    assert readiness.json()["publishable"] is False

    # Replace the draft with a second published course: now publishable.
    removed = await client.request(
        "DELETE", f"/api/v1/learning-paths/{path_id}/courses/{draft_id}", headers=auth
    )
    assert removed.status_code == 200, removed.text
    course_b = await _published_course(client, auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/courses", json={"course_id": course_b}, headers=auth
    )
    published = await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=auth)
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"


async def test_published_path_membership_is_frozen_and_a_late_add_degrades_not_403s(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """F2 (docs/research/p5-review-findings.md): editing a published
    path's membership used to be able to strand an existing purchaser —
    a course added after purchase has no reachable Enrolment, and
    get_path_progress used to raise Forbidden the moment it hit one,
    failing the whole rollup for every other course too. add_course_to_
    path/remove_course_from_path now refuse outright while published;
    this test also proves the defence-in-depth half still holds for a
    path that somehow reaches that state anyway (unpublish, edit,
    republish, exactly the workflow the refusal message tells an admin
    to use) — the learner's progress page degrades that one row instead
    of 403ing the whole response."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    admin_auth = {"Authorization": f"Bearer {admin_token}"}

    course_a = await _published_course(client, admin_auth)
    course_b = await _published_course(client, admin_auth)
    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "Frozen Membership Path"}, headers=admin_auth
        )
    ).json()
    path_id = path["id"]
    for course_id in (course_a, course_b):
        await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": course_id},
            headers=admin_auth,
        )
    await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=admin_auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=admin_auth,
    )

    # Refused outright while published — add and remove both.
    course_c = await _published_course(client, admin_auth)
    add_refused = await client.post(
        f"/api/v1/learning-paths/{path_id}/courses",
        json={"course_id": course_c},
        headers=admin_auth,
    )
    assert add_refused.status_code == 400, add_refused.text
    remove_refused = await client.request(
        "DELETE", f"/api/v1/learning-paths/{path_id}/courses/{course_a}", headers=admin_auth
    )
    assert remove_refused.status_code == 400, remove_refused.text

    # A real purchaser, bought before the membership edit below.
    product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": f"frozen-path-{uuid.uuid4().hex[:8]}",
                "name": "Frozen Membership Path Product",
                "learning_path_id": path_id,
            },
            headers=admin_auth,
        )
    ).json()
    price = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "800.00"},
            headers=admin_auth,
        )
    ).json()
    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=admin_auth
    )
    finance_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    finance_auth = {"Authorization": f"Bearer {finance_token}"}
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
    checkout = await client.post(
        f"/api/v1/orders/{order.json()['id']}/checkout/eft", headers=buyer_auth
    )
    assert checkout.status_code == 200, checkout.text
    await client.post(
        f"/api/v1/orders/{order.json()['id']}/payment-proof",
        files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
        headers=buyer_auth,
    )
    approved = await client.post(
        f"/api/v1/payments/{checkout.json()['payment_id']}/approve",
        headers={**finance_auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approved.status_code == 200, approved.text
    path_enrolment_id = next(
        r
        for r in (await client.get("/api/v1/path-enrolments", headers=buyer_auth)).json()
        if r["learning_path_id"] == path_id
    )["path_enrolment_id"]

    # Defence-in-depth: unpublish, add a member the existing purchaser
    # was never enrolled in, republish — the workflow the refusal above
    # itself recommends. get_path_progress must degrade, not 403.
    await client.post(f"/api/v1/learning-paths/{path_id}/unpublish", headers=admin_auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/courses",
        json={"course_id": course_c},
        headers=admin_auth,
    )
    await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=admin_auth)

    progress = await client.get(
        f"/api/v1/path-enrolments/{path_enrolment_id}/progress", headers=buyer_auth
    )
    assert progress.status_code == 200, progress.text
    rows_by_course = {c["course_id"]: c for c in progress.json()["courses"]}
    assert len(rows_by_course) == 3
    assert rows_by_course[course_c]["enrolment_id"] is None
    assert rows_by_course[course_c]["progress_percent"] == 0
    assert rows_by_course[course_a]["enrolment_id"] is not None


async def test_a_path_bought_after_its_courses_are_already_complete_still_completes(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """F5 (docs/research/p5-review-findings.md): completion used to be
    detected only inside complete_lesson, so a learner who finished both
    courses individually first, then bought the bundling path for its
    credential, got a PathEnrolment stuck at 100% forever — no lesson
    ever completes again to trigger the check. get_path_progress now
    read-repairs this the first time the progress page is opened."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    admin_auth = {"Authorization": f"Bearer {admin_token}"}
    finance_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    finance_auth = {"Authorization": f"Bearer {finance_token}"}
    buyer_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    buyer_auth = {"Authorization": f"Bearer {buyer_token}"}

    course_a = await _published_course(client, admin_auth)
    course_b = await _published_course(client, admin_auth)

    # Buy and complete both courses individually — before the path that
    # will later bundle them even exists.
    for course_id in (course_a, course_b):
        await client.post(
            f"/api/v1/courses/{course_id}/tenant-assignments",
            json={"is_bespoke": False},
            headers=admin_auth,
        )
        product_resp = await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": f"standalone-{uuid.uuid4().hex[:8]}",
                "name": "Standalone Course Product",
                "course_id": course_id,
            },
            headers=admin_auth,
        )
        assert product_resp.status_code == 201, product_resp.text
        product = product_resp.json()
        price = (
            await client.post(
                f"/api/v1/catalogue/products/{product['id']}/prices",
                json={"currency": "ZAR", "unit_amount": "400.00"},
                headers=admin_auth,
            )
        ).json()
        await client.patch(
            f"/api/v1/catalogue/products/{product['id']}",
            json={"is_active": True},
            headers=admin_auth,
        )
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
        checkout = await client.post(
            f"/api/v1/orders/{order.json()['id']}/checkout/eft", headers=buyer_auth
        )
        assert checkout.status_code == 200, checkout.text
        await client.post(
            f"/api/v1/orders/{order.json()['id']}/payment-proof",
            files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
            headers=buyer_auth,
        )
        approved = await client.post(
            f"/api/v1/payments/{checkout.json()['payment_id']}/approve",
            headers={**finance_auth, "Idempotency-Key": uuid.uuid4().hex},
        )
        assert approved.status_code == 200, approved.text
        for lesson_id in await _lessons_for_course(tenant_session_factory, tenant_id, course_id):
            await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=buyer_auth)
            complete = await client.post(
                f"/api/v1/lessons/{lesson_id}/complete", headers=buyer_auth
            )
            assert complete.status_code == 200, complete.text

    # Now build and sell the path bundling those same two, already-
    # completed courses.
    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "Retroactive Path"}, headers=admin_auth
        )
    ).json()
    path_id = path["id"]
    for course_id in (course_a, course_b):
        await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": course_id},
            headers=admin_auth,
        )
    await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=admin_auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=admin_auth,
    )
    cert_template_id = uuid.uuid4()
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "INSERT INTO certificate_templates "
                "(id, title, issuer_name, signatory_name, signatory_title, cpd_points) "
                "VALUES (:id, 'Retroactive Path Certificate', 'TTLI', 'Dr. Themba', 'Director', 5)"
            ),
            {"id": cert_template_id},
        )
    await client.patch(
        f"/api/v1/learning-paths/{path_id}",
        json={"certificate_template_id": str(cert_template_id)},
        headers=admin_auth,
    )
    path_product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": f"retroactive-path-{uuid.uuid4().hex[:8]}",
                "name": "Retroactive Path Product",
                "learning_path_id": path_id,
            },
            headers=admin_auth,
        )
    ).json()
    path_price = (
        await client.post(
            f"/api/v1/catalogue/products/{path_product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "1200.00"},
            headers=admin_auth,
        )
    ).json()
    await client.patch(
        f"/api/v1/catalogue/products/{path_product['id']}",
        json={"is_active": True},
        headers=admin_auth,
    )
    path_order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": path_price["id"], "quantity": 1}],
        },
        headers={**buyer_auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert path_order.status_code == 201, path_order.text
    path_checkout = await client.post(
        f"/api/v1/orders/{path_order.json()['id']}/checkout/eft", headers=buyer_auth
    )
    assert path_checkout.status_code == 200, path_checkout.text
    await client.post(
        f"/api/v1/orders/{path_order.json()['id']}/payment-proof",
        files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
        headers=buyer_auth,
    )
    path_approved = await client.post(
        f"/api/v1/payments/{path_checkout.json()['payment_id']}/approve",
        headers={**finance_auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert path_approved.status_code == 200, path_approved.text

    path_enrolment_id = next(
        r
        for r in (await client.get("/api/v1/path-enrolments", headers=buyer_auth)).json()
        if r["learning_path_id"] == path_id
    )["path_enrolment_id"]
    # Before the fix: this would return progress_percent == 100 with
    # completed_at == None, forever — no future lesson-completion event
    # can ever fire for this path again.
    progress = await client.get(
        f"/api/v1/path-enrolments/{path_enrolment_id}/progress", headers=buyer_auth
    )
    assert progress.status_code == 200, progress.text
    body = progress.json()
    assert body["progress_percent"] == 100
    assert body["completed_at"] is not None

    credentials = await client.get(
        f"/api/v1/path-enrolments/{path_enrolment_id}/credentials", headers=buyer_auth
    )
    assert credentials.status_code == 200, credentials.text
    assert credentials.json()["certificate"] is not None
    assert credentials.json()["certificate"]["pdf_available"] is True

    # Idempotent: a second read doesn't issue a second certificate.
    async with tenant_session_factory(tenant_id) as s:
        certs = (
            await s.execute(
                sa.text("SELECT COUNT(*) FROM certificates WHERE path_enrolment_id = :p"),
                {"p": path_enrolment_id},
            )
        ).scalar_one()
    await client.get(f"/api/v1/path-enrolments/{path_enrolment_id}/progress", headers=buyer_auth)
    async with tenant_session_factory(tenant_id) as s:
        certs_after = (
            await s.execute(
                sa.text("SELECT COUNT(*) FROM certificates WHERE path_enrolment_id = :p"),
                {"p": path_enrolment_id},
            )
        ).scalar_one()
    assert certs == 1
    assert certs_after == 1


async def test_reorder_courses_and_tenant_assignment(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    auth = {"Authorization": f"Bearer {token}"}

    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "Reorder Test Path"}, headers=auth
        )
    ).json()
    path_id = path["id"]

    course_a = await _published_course(client, auth)
    course_b = await _published_course(client, auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/courses", json={"course_id": course_a}, headers=auth
    )
    await client.post(
        f"/api/v1/learning-paths/{path_id}/courses", json={"course_id": course_b}, headers=auth
    )

    listed = await client.get(f"/api/v1/learning-paths/{path_id}/courses", headers=auth)
    assert [row["course_id"] for row in listed.json()["items"]] == [course_a, course_b]

    reordered = await client.post(
        f"/api/v1/learning-paths/{path_id}/courses/reorder",
        json={"ordered_course_ids": [course_b, course_a]},
        headers=auth,
    )
    assert reordered.status_code == 200, reordered.text
    assert [row["course_id"] for row in reordered.json()["items"]] == [course_b, course_a]

    # Assigning to a tenant before publish is refused.
    early_assign = await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=auth,
    )
    assert early_assign.status_code == 400

    published = await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=auth)
    assert published.status_code == 200, published.text

    assigned = await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": True},
        headers=auth,
    )
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["is_bespoke"] is True

    # F6 (docs/research/p5-review-findings.md): the read half of tenant
    # assignment — assign_path_to_tenant previously had no way for the
    # admin editor to ever show whether a path was already assigned.
    listed_assignments = await client.get("/api/v1/tenant-path-assignments", headers=auth)
    assert listed_assignments.status_code == 200, listed_assignments.text
    row = next(r for r in listed_assignments.json()["items"] if r["learning_path_id"] == path_id)
    assert row["is_bespoke"] is True
    assert row["learning_path_title"] == "Reorder Test Path"


async def test_clearing_a_paths_certificate_template(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """F6: update_learning_path's PATCH treats `None` as "leave
    unchanged", so there was previously no way to detach a certificate
    template once attached — the same gap course_wizard.py's own
    clear-templates endpoint exists to close."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    auth = {"Authorization": f"Bearer {token}"}

    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "Clearable Cert Path"}, headers=auth
        )
    ).json()
    path_id = path["id"]

    cert_template_id = uuid.uuid4()
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "INSERT INTO certificate_templates "
                "(id, title, issuer_name, signatory_name, signatory_title, cpd_points) "
                "VALUES (:id, 'Clearable Cert', 'TTLI', 'Dr. Themba', 'Director', 2)"
            ),
            {"id": cert_template_id},
        )
    attached = await client.patch(
        f"/api/v1/learning-paths/{path_id}",
        json={"certificate_template_id": str(cert_template_id)},
        headers=auth,
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["certificate_template_id"] == str(cert_template_id)

    cleared = await client.post(
        f"/api/v1/learning-paths/{path_id}/clear-certificate-template", headers=auth
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["certificate_template_id"] is None


async def test_adding_a_course_after_a_removal_does_not_collide_positions(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """F6: position used to come from count(*), which collides with an
    existing position once a mid-list removal has happened — removing
    course A of [A, B] and adding C used to give C position 1, the same
    position B already holds. Now max(position) + 1."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    auth = {"Authorization": f"Bearer {token}"}

    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "No Position Collision"}, headers=auth
        )
    ).json()
    path_id = path["id"]

    course_a = await _published_course(client, auth)
    course_b = await _published_course(client, auth)
    for course_id in (course_a, course_b):
        await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": course_id},
            headers=auth,
        )

    removed = await client.request(
        "DELETE", f"/api/v1/learning-paths/{path_id}/courses/{course_a}", headers=auth
    )
    assert removed.status_code == 200, removed.text

    course_c = await _published_course(client, auth)
    added = await client.post(
        f"/api/v1/learning-paths/{path_id}/courses",
        json={"course_id": course_c},
        headers=auth,
    )
    assert added.status_code == 201, added.text
    ordered_ids = [row["course_id"] for row in added.json()["items"]]
    assert ordered_ids == [course_b, course_c]


async def test_path_purchase_grants_all_member_enrolments_via_eft(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Phase 2's whole point: buying a path through the real EFT approve
    flow grants entitlement + enrolment for every member course, plus a
    path_enrolment anchor row — the commerce bridge works end to end,
    not just the authoring API. Mirrors test_catalogue.py's own
    course-purchase test shape."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    admin_auth = {"Authorization": f"Bearer {admin_token}"}

    course_a = await _published_course(client, admin_auth)
    course_b = await _published_course(client, admin_auth)

    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "EFT Purchase Path"}, headers=admin_auth
        )
    ).json()
    path_id = path["id"]
    for course_id in (course_a, course_b):
        added = await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": course_id},
            headers=admin_auth,
        )
        assert added.status_code == 201, added.text
    published = await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=admin_auth)
    assert published.status_code == 200, published.text
    await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=admin_auth,
    )

    product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": f"path-prod-{uuid.uuid4().hex[:8]}",
                "name": "EFT Path Product",
                "learning_path_id": path_id,
            },
            headers=admin_auth,
        )
    ).json()
    assert product["kind"] == "path"
    assert product["learning_path_id"] == path_id
    price = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "3000.00"},
            headers=admin_auth,
        )
    ).json()
    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=admin_auth
    )

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
    payment_id = checkout.json()["payment_id"]

    proof = await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
        headers=buyer_auth,
    )
    assert proof.status_code == 204, proof.text

    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    approved = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approved.status_code == 200, approved.text

    enrolments = await client.get("/api/v1/enrolments", headers=buyer_auth)
    assert enrolments.status_code == 200, enrolments.text
    enrolled_course_ids = {row["course_id"] for row in enrolments.json()}
    assert course_a in enrolled_course_ids
    assert course_b in enrolled_course_ids

    # path_enrolments and the course-kind entitlements it depends on have
    # no read endpoint yet (that's Phase 3/4) — asserted directly.
    async with tenant_session_factory(tenant_id) as s:
        path_enrolment = (
            await s.execute(
                sa.text("SELECT id, completed_at FROM path_enrolments WHERE learning_path_id = :p"),
                {"p": path_id},
            )
        ).first()
        course_entitlement_count = (
            await s.execute(
                sa.text(
                    "SELECT count(*) FROM entitlements WHERE kind = 'course' "
                    "AND target_id IN (:a, :b) AND source_order_id = :o"
                ),
                {"a": course_a, "b": course_b, "o": order_id},
            )
        ).scalar_one()
    assert path_enrolment is not None
    assert path_enrolment.completed_at is None
    assert course_entitlement_count == 2


async def test_public_path_browsing_respects_publish_and_assignment(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """`GET /public/learning-paths` is unauthenticated — a draft or
    unassigned path must stay invisible, the same visibility rule
    `_visible_course` already enforces for courses."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    admin_auth = {"Authorization": f"Bearer {admin_token}"}

    course_a = await _published_course(client, admin_auth)
    course_b = await _published_course(client, admin_auth)
    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "Public Browse Path"}, headers=admin_auth
        )
    ).json()
    path_id = path["id"]
    for course_id in (course_a, course_b):
        await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": course_id},
            headers=admin_auth,
        )

    # Draft, unassigned: invisible.
    before = await client.get("/api/v1/public/learning-paths")
    assert before.status_code == 200
    assert all(p["id"] != path_id for p in before.json()["items"])
    detail_before = await client.get(f"/api/v1/public/learning-paths/{path_id}")
    assert detail_before.status_code == 404

    await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=admin_auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=admin_auth,
    )

    listed = await client.get("/api/v1/public/learning-paths")
    assert listed.status_code == 200
    card = next(p for p in listed.json()["items"] if p["id"] == path_id)
    assert card["course_count"] == 2
    assert card["price"] is None  # no product/price created for it in this test

    detail = await client.get(f"/api/v1/public/learning-paths/{path_id}")
    assert detail.status_code == 200, detail.text
    assert [c["course_id"] for c in detail.json()["courses"]] == [course_a, course_b]


async def test_path_product_authoring_and_admin_listing(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The admin editor's "Sell this path" section: create a product
    bound to a path, price it, activate it — and confirm `GET /catalogue/
    products` (the admin list every product page loads) actually returns
    it with the path linkage populated. This is the one admin list
    endpoint nothing else in the suite exercises with a real path-kind
    row present."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    auth = {"Authorization": f"Bearer {token}"}

    path = (
        await client.post("/api/v1/learning-paths", json={"title": "Sellable Path"}, headers=auth)
    ).json()
    path_id = path["id"]
    for _ in range(2):
        member = await _published_course(client, auth)
        await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": member},
            headers=auth,
        )
    await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=auth)
    # _assert_path_sellable (mirrors _assert_course_sellable) requires the
    # path be assigned to this tenant before a product can sell it.
    await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=auth,
    )

    product = await client.post(
        "/api/v1/catalogue/products",
        json={
            "slug": f"sellable-path-{uuid.uuid4().hex[:8]}",
            "name": "Sellable Path Product",
            "learning_path_id": path_id,
        },
        headers=auth,
    )
    assert product.status_code == 201, product.text
    body = product.json()
    assert body["kind"] == "path"
    assert body["learning_path_id"] == path_id
    assert body["course_id"] is None

    price = await client.post(
        f"/api/v1/catalogue/products/{body['id']}/prices",
        json={"currency": "ZAR", "unit_amount": "2500.00"},
        headers=auth,
    )
    assert price.status_code == 201, price.text

    activated = await client.patch(
        f"/api/v1/catalogue/products/{body['id']}", json={"is_active": True}, headers=auth
    )
    assert activated.status_code == 200, activated.text

    # The bug this test exists to pin: list_all_products' SELECT gained a
    # third column (LearningPath.title) but a later unpacking loop still
    # assumed two, raising ValueError on any real row — invisible to the
    # rest of the suite because nothing else GETs this list with a
    # path-kind product actually present.
    listed = await client.get("/api/v1/catalogue/products", headers=auth)
    assert listed.status_code == 200, listed.text
    row = next(p for p in listed.json()["items"] if p["id"] == body["id"])
    assert row["learning_path_id"] == path_id
    assert row["learning_path_title"] == "Sellable Path"
    assert row["is_active"] is True
    assert len(row["prices"]) == 1

    # A product can't sell both a course and a path.
    course = await _published_course(client, auth)
    rejected = await client.post(
        "/api/v1/catalogue/products",
        json={
            "slug": f"both-{uuid.uuid4().hex[:8]}",
            "name": "Both",
            "course_id": course,
            "learning_path_id": path_id,
        },
        headers=auth,
    )
    assert rejected.status_code == 400, rejected.text

    # F3: the same "never both" rule applies to PATCH, not just POST — a
    # course product can't be edited to also carry a learning_path_id,
    # and vice versa (docs/research/p5-review-findings.md).
    await client.post(
        f"/api/v1/courses/{course}/tenant-assignments", json={"is_bespoke": False}, headers=auth
    )
    course_product = await client.post(
        "/api/v1/catalogue/products",
        json={
            "slug": f"course-only-{uuid.uuid4().hex[:8]}",
            "name": "Course Only",
            "course_id": course,
        },
        headers=auth,
    )
    assert course_product.status_code == 201, course_product.text
    course_product_id = course_product.json()["id"]

    patch_course_to_path = await client.patch(
        f"/api/v1/catalogue/products/{course_product_id}",
        json={"learning_path_id": path_id},
        headers=auth,
    )
    assert patch_course_to_path.status_code == 400, patch_course_to_path.text

    patch_path_to_course = await client.patch(
        f"/api/v1/catalogue/products/{body['id']}",
        json={"course_id": course},
        headers=auth,
    )
    assert patch_path_to_course.status_code == 400, patch_path_to_course.text

    # Neither refusal mutated anything — both products still sell what
    # they sold before the rejected PATCH.
    unchanged_course = await client.get("/api/v1/catalogue/products", headers=auth)
    rows_by_id = {p["id"]: p for p in unchanged_course.json()["items"]}
    assert rows_by_id[course_product_id]["learning_path_id"] is None
    assert rows_by_id[body["id"]]["course_id"] is None


async def test_organisation_order_refuses_a_path_product(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """F1 (docs/research/p5-review-findings.md): organisations.py's seat
    pool (assign_seat, _pool_entitlements, list_assigned_seats) only ever
    knows kind == "course" — a path-kind entitlement granted to an
    organisation's pool would be undeliverable forever. create_order
    must refuse the line before any money moves, not let it reach
    fulfilment and silently strand it there."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    admin_auth = {"Authorization": f"Bearer {admin_token}"}

    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "Org-Refused Path"}, headers=admin_auth
        )
    ).json()
    path_id = path["id"]
    for _ in range(2):
        member = await _published_course(client, admin_auth)
        await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": member},
            headers=admin_auth,
        )
    await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=admin_auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=admin_auth,
    )
    product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": f"org-refused-path-{uuid.uuid4().hex[:8]}",
                "name": "Org-Refused Path Product",
                "learning_path_id": path_id,
            },
            headers=admin_auth,
        )
    ).json()
    price = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "1000.00"},
            headers=admin_auth,
        )
    ).json()
    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=admin_auth
    )

    org_admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    org_admin_auth = {"Authorization": f"Bearer {org_admin_token}"}
    org = await client.post(
        "/api/v1/organisations", json={"name": "Path-Curious Org"}, headers=org_admin_auth
    )
    assert org.status_code == 201, org.text
    org_id = org.json()["id"]

    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "registered_business",
            "lines": [{"price_id": price["id"], "quantity": 3}],
            "organisation_id": org_id,
        },
        headers={**org_admin_auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert order.status_code == 400, order.text


async def _lessons_for_course(tenant_session_factory, tenant_id, course_id: str) -> list[str]:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT l.id FROM lessons l JOIN modules m ON m.id = l.module_id "
                    "WHERE m.course_id = :c ORDER BY l.position"
                ),
                {"c": course_id},
            )
        ).all()
    return [str(row[0]) for row in rows]


async def test_completing_every_member_course_issues_one_path_certificate(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Phase 3's whole point: completing the last lesson of the last
    member course completes the path_enrolment and issues exactly one
    certificate — through the real lesson-completion API, the same way
    test_credentials.py proves course completion does. The freshly
    authored courses here carry no completion_rules (their
    default), so no minimum_time_seconds backdating trick is needed —
    start-then-complete succeeds immediately, unlike the seeded demo
    course test_credentials.py uses."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
    )
    admin_auth = {"Authorization": f"Bearer {admin_token}"}

    course_a = await _published_course(client, admin_auth)
    course_b = await _published_course(client, admin_auth)

    path = (
        await client.post(
            "/api/v1/learning-paths", json={"title": "Completable Path"}, headers=admin_auth
        )
    ).json()
    path_id = path["id"]
    for course_id in (course_a, course_b):
        await client.post(
            f"/api/v1/learning-paths/{path_id}/courses",
            json={"course_id": course_id},
            headers=admin_auth,
        )
    await client.post(f"/api/v1/learning-paths/{path_id}/publish", headers=admin_auth)
    await client.post(
        f"/api/v1/learning-paths/{path_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers=admin_auth,
    )

    cert_template_id = uuid.uuid4()
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "INSERT INTO certificate_templates "
                "(id, title, issuer_name, signatory_name, signatory_title, cpd_points) "
                "VALUES (:id, 'Path Certificate', 'TTLI', 'Dr. Themba', 'Director', 3)"
            ),
            {"id": cert_template_id},
        )
    await client.patch(
        f"/api/v1/learning-paths/{path_id}",
        json={"certificate_template_id": str(cert_template_id)},
        headers=admin_auth,
    )

    product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": f"completable-path-{uuid.uuid4().hex[:8]}",
                "name": "Completable Path Product",
                "learning_path_id": path_id,
            },
            headers=admin_auth,
        )
    ).json()
    price = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "1000.00"},
            headers=admin_auth,
        )
    ).json()
    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", json={"is_active": True}, headers=admin_auth
    )

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
    order_id = order.json()["id"]
    checkout = await client.post(f"/api/v1/orders/{order_id}/checkout/eft", headers=buyer_auth)
    payment_id = checkout.json()["payment_id"]
    await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
        headers=buyer_auth,
    )
    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    approved = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approved.status_code == 200, approved.text

    # The path_enrolment already exists at purchase time (Phase 2), so
    # the learner's own list shows it before any lesson is touched.
    own_paths = await client.get("/api/v1/path-enrolments", headers=buyer_auth)
    assert own_paths.status_code == 200, own_paths.text
    own_row = next(r for r in own_paths.json() if r["learning_path_id"] == path_id)
    assert own_row["learning_path_title"] == "Completable Path"
    assert own_row["course_count"] == 2
    assert own_row["completed_at"] is None
    path_enrolment_id = own_row["path_enrolment_id"]

    for course_id in (course_a, course_b):
        for lesson_id in await _lessons_for_course(tenant_session_factory, tenant_id, course_id):
            start = await client.post(f"/api/v1/lessons/{lesson_id}/start", headers=buyer_auth)
            assert start.status_code == 204, start.text
            complete = await client.post(
                f"/api/v1/lessons/{lesson_id}/complete", headers=buyer_auth
            )
            assert complete.status_code == 200, complete.text
        # One course down, one to go: the rollup is an average, so it
        # should read as neither 0 nor 100 yet.
        mid_progress = await client.get(
            f"/api/v1/path-enrolments/{path_enrolment_id}/progress", headers=buyer_auth
        )
        assert mid_progress.status_code == 200, mid_progress.text
        if course_id == course_a:
            assert 0 < mid_progress.json()["progress_percent"] < 100

    final_progress = await client.get(
        f"/api/v1/path-enrolments/{path_enrolment_id}/progress", headers=buyer_auth
    )
    assert final_progress.status_code == 200, final_progress.text
    final_body = final_progress.json()
    assert final_body["progress_percent"] == 100
    assert final_body["completed_at"] is not None
    assert len(final_body["courses"]) == 2
    assert all(c["progress_percent"] == 100 for c in final_body["courses"])

    # The learner UI's route to the certificate: the path-credentials
    # endpoint added alongside the /learn/paths/[id] page.
    own_credentials = await client.get(
        f"/api/v1/path-enrolments/{path_enrolment_id}/credentials", headers=buyer_auth
    )
    assert own_credentials.status_code == 200, own_credentials.text
    own_credentials_body = own_credentials.json()
    assert own_credentials_body["certificate"] is not None
    assert own_credentials_body["certificate"]["pdf_available"] is True
    assert own_credentials_body["badge"] is None

    async with tenant_session_factory(tenant_id) as s:
        path_enrolment = (
            await s.execute(
                sa.text("SELECT completed_at FROM path_enrolments WHERE learning_path_id = :p"),
                {"p": path_id},
            )
        ).first()
        certificates = (
            await s.execute(
                sa.text(
                    "SELECT id, pdf_object_key, verification_token_encrypted FROM certificates "
                    "WHERE path_enrolment_id IS NOT NULL AND tenant_id = :t "
                    "AND path_enrolment_id IN "
                    "(SELECT id FROM path_enrolments WHERE learning_path_id = :p)"
                ),
                {"t": tenant_id, "p": path_id},
            )
        ).all()
    assert path_enrolment is not None
    assert path_enrolment.completed_at is not None
    assert len(certificates) == 1  # exactly one, not one per member course
    certificate = certificates[0]
    assert certificate.pdf_object_key is not None

    # New certificates default to private (same as a course's) — the
    # holder has to opt in before /verify will show it, exactly the
    # pattern test_credentials.py's own tests exercise.
    made_public = await client.patch(
        f"/api/v1/certificates/{certificate.id}",
        json={"visibility": "public"},
        headers=buyer_auth,
    )
    assert made_public.status_code == 200, made_public.text

    raw_token = crypto.decrypt(certificate.verification_token_encrypted)
    verified = await client.get(f"/api/v1/verify/{raw_token}")
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["found"] is True
    assert body["is_learning_path"] is True
    assert body["course_title"] == "Completable Path"
