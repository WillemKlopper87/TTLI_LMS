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
