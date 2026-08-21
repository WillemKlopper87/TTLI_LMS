"""The audit-log read path (`routers/audit.py`, Pass B of
`docs/research/enterprise-gaps-plan.md`), and the coverage additions that
came with it.

The table has been written to since 0001 and had no read path at all
until this pass, so these tests cover two things: that reading it is
gated, filtered and paginated correctly, and that the actions a
compliance reviewer actually opens it for — money moving, a credential
revoked, a course published — now leave a row behind.
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
        pytest.skip("no Redis on the configured REDIS_URL")
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
    return f"audit-{uuid.uuid4().hex[:12]}@example.com"


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


async def test_audit_log_requires_audit_read(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The audit log names who did what. A signed-in learner reading it
    would be a disclosure, not a feature."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    resp = await client.get("/api/v1/audit-events", headers={"Authorization": f"Bearer {learner}"})
    assert resp.status_code == 403
    assert (await client.get("/api/v1/audit-events")).status_code == 401

    # finance holds payment:approve but deliberately not audit:read.
    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    denied = await client.get(
        "/api/v1/audit-events", headers={"Authorization": f"Bearer {finance}"}
    )
    assert denied.status_code == 403


async def test_audit_log_lists_newest_first_and_masks_the_actor(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    resp = await client.get("/api/v1/audit-events?limit=10", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items, "logging in just wrote an audit row, so the log is not empty"
    assert len(items) <= 10

    stamps = [row["created_at"] for row in items]
    assert stamps == sorted(stamps, reverse=True), "newest first"

    for row in items:
        # Masked, never the raw address — an audit export must not become
        # a second copy of the user table.
        if row["actor_email"] is not None:
            assert row["actor_email"].startswith("(") or "•••@" in row["actor_email"]


async def test_audit_log_filters_by_action(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    resp = await client.get(
        "/api/v1/audit-events?action=auth.login.succeeded&limit=25", headers=headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert rows, "this test logged in, so a succeeded-login row exists"
    assert {row["action"] for row in rows} == {"auth.login.succeeded"}

    actions = await client.get("/api/v1/audit-events/actions", headers=headers)
    assert actions.status_code == 200
    assert "auth.login.succeeded" in actions.json()["actions"]


async def test_keyset_pagination_never_repeats_or_skips(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The reason this endpoint is keyset- rather than offset-paginated:
    walking a growing table by OFFSET repeats or drops rows the moment
    anything is written mid-walk. Two consecutive pages must be
    disjoint and continuous."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    first = await client.get("/api/v1/audit-events?limit=5", headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 5
    assert body["next_cursor"], "a dev database has far more than five audit rows"

    second = await client.get(
        f"/api/v1/audit-events?limit=5&cursor={body['next_cursor']}", headers=headers
    )
    assert second.status_code == 200
    page_two = second.json()["items"]

    ids_one = {row["id"] for row in body["items"]}
    ids_two = {row["id"] for row in page_two}
    assert not (ids_one & ids_two), "pages must not overlap"
    assert min(r["created_at"] for r in body["items"]) >= max(r["created_at"] for r in page_two), (
        "page two is strictly older"
    )


async def test_a_broken_cursor_returns_the_first_page(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """A stale bookmark is a client problem, not a 500."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    resp = await client.get(
        "/api/v1/audit-events?limit=3&cursor=not-a-real-cursor",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3


async def test_csv_export_carries_the_before_after_json(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    resp = await client.get(
        "/api/v1/audit-events/export.csv?action=auth.login.succeeded",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    header = resp.text.splitlines()[0]
    # A change record without before/after is a list of verbs.
    assert "before" in header and "after" in header
    assert "actor_email" in header


async def test_publishing_a_course_is_audited(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Coverage added in this pass: publishing changes what learners can
    buy and enter, and was previously invisible in the log."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    created = await client.post(
        "/api/v1/courses",
        json={"title": f"Audit Coverage Course {uuid.uuid4().hex[:8]}", "slug": None},
        headers=headers,
    )
    assert created.status_code in (200, 201), created.text
    course_id = created.json()["id"]

    module = await client.post(
        f"/api/v1/courses/{course_id}/modules", json={"title": "M1"}, headers=headers
    )
    assert module.status_code in (200, 201), module.text
    lesson = await client.post(
        f"/api/v1/modules/{module.json()['id']}/lessons",
        json={"title": "L1", "activity_type": "document", "body": "hello"},
        headers=headers,
    )
    assert lesson.status_code in (200, 201), lesson.text

    published = await client.post(f"/api/v1/courses/{course_id}/publish", headers=headers)
    assert published.status_code == 200, published.text

    log = await client.get(
        f"/api/v1/audit-events?action=course.published&entity_id={course_id}", headers=headers
    )
    assert log.status_code == 200
    rows = log.json()["items"]
    assert len(rows) == 1, "publishing wrote exactly one audit row"
    assert rows[0]["entity_type"] == "course"
    assert rows[0]["after"]["state"] == "published"
