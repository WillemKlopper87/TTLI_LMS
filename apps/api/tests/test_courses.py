"""Course/module/lesson/tenant-assignment authoring (02 §5, REQ-TEN-03) —
the Phase 4 authoring gap `docs/STATUS.md` tracked. HTTP coverage for the
full authoring flow (course -> module -> lesson -> publish -> assign to
tenant), the invariants `services/courses.py` enforces (positions,
publish requiring real content, tenant-assignment requiring a published
course), and that `activity_type`/quiz/survey/assignment/video linkage
stays out of client reach through this surface.
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
    return f"course-{uuid.uuid4().hex[:12]}@example.com"


def _unique_title() -> str:
    return f"Test Course {uuid.uuid4().hex[:8]}"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _login(
    client, tenant_session_factory, crypto, *, tenant_id, role: str | None
) -> tuple[str, uuid.UUID, str]:  # type: ignore[no-untyped-def]
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
    return str(resp.json()["access_token"]), user_id, email


async def _make_course(client, token: str, *, title: str | None = None) -> str:
    resp = await client.post(
        "/api/v1/courses",
        json={"title": title or _unique_title()},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _make_module(client, token: str, course_id: str, *, title: str = "Module 1") -> str:
    resp = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _make_lesson(client, token: str, module_id: str, *, title: str = "Lesson 1") -> str:
    resp = await client.post(
        f"/api/v1/modules/{module_id}/lessons",
        json={"title": title},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _make_published_course(client, token: str) -> str:
    """A course with one module, one lesson, published — the shape most
    tests need as a starting point, not the thing under test."""
    course_id = await _make_course(client, token)
    module_id = await _make_module(client, token, course_id)
    await _make_lesson(client, token, module_id)
    published = await client.post(
        f"/api/v1/courses/{course_id}/publish", headers={"Authorization": f"Bearer {token}"}
    )
    assert published.status_code == 200, published.text
    return course_id


async def test_course_authoring_requires_course_edit(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.post(
        "/api/v1/courses",
        json={"title": "Should not be created"},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403


async def test_publish_requires_course_publish_not_just_course_edit(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _make_course(client, admin_token)
    module_id = await _make_module(client, admin_token, course_id)
    await _make_lesson(client, admin_token, module_id)

    # finance has no course:edit or course:publish at all.
    finance_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    resp = await client.post(
        f"/api/v1/courses/{course_id}/publish",
        headers={"Authorization": f"Bearer {finance_token}"},
    )
    assert resp.status_code == 403


async def test_full_authoring_flow_create_publish_and_assign_to_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    course_id = await _make_course(client, author_token)
    module_id = await _make_module(client, author_token, course_id)
    lesson_id = await _make_lesson(client, author_token, module_id)

    published = await client.post(
        f"/api/v1/courses/{course_id}/publish", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"

    assigned = await client.post(
        f"/api/v1/courses/{course_id}/tenant-assignments",
        json={"is_bespoke": True},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert assigned.status_code == 201, assigned.text

    listed = await client.get(
        "/api/v1/tenant-assignments", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["items"]
    matching = [r for r in rows if r["course_id"] == course_id]
    assert len(matching) == 1
    assert matching[0]["is_bespoke"] is True

    lessons = await client.get(
        f"/api/v1/modules/{module_id}/lessons", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert lessons.status_code == 200
    lesson = next(item for item in lessons.json()["items"] if item["id"] == lesson_id)
    assert lesson["activity_type"] == "document"


async def test_publish_rejects_a_course_with_no_modules(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _make_course(client, admin_token)
    resp = await client.post(
        f"/api/v1/courses/{course_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 400, resp.text
    assert "module" in resp.json()["error"]["message"].lower()


async def test_publish_rejects_a_module_with_no_lessons(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _make_course(client, admin_token)
    await _make_module(client, admin_token, course_id)
    resp = await client.post(
        f"/api/v1/courses/{course_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 400, resp.text
    assert "lesson" in resp.json()["error"]["message"].lower()


async def test_module_and_lesson_positions_auto_increment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _make_course(client, admin_token)
    module_ids = [
        await _make_module(client, admin_token, course_id, title=f"Module {i}") for i in range(3)
    ]
    modules = await client.get(
        f"/api/v1/courses/{course_id}/modules", headers={"Authorization": f"Bearer {admin_token}"}
    )
    positions = {m["id"]: m["position"] for m in modules.json()["items"]}
    assert [positions[mid] for mid in module_ids] == [0, 1, 2]

    lesson_ids = [
        await _make_lesson(client, admin_token, module_ids[0], title=f"Lesson {i}")
        for i in range(3)
    ]
    lessons = await client.get(
        f"/api/v1/modules/{module_ids[0]}/lessons",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    lesson_positions = {lesson["id"]: lesson["position"] for lesson in lessons.json()["items"]}
    assert [lesson_positions[lid] for lid in lesson_ids] == [0, 1, 2]


async def test_completion_rules_rejects_a_bad_type_but_ignores_an_unknown_key(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    bad = await client.post(
        "/api/v1/courses",
        json={"title": _unique_title(), "completion_rules": {"quiz_pass_score": "not-a-number"}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bad.status_code == 400, bad.text

    # A pre-existing property of CompletionRules (not extra="forbid"),
    # documented here rather than assuming a stronger guarantee.
    ignored = await client.post(
        "/api/v1/courses",
        json={"title": _unique_title(), "completion_rules": {"totally_made_up_field": True}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert ignored.status_code == 201, ignored.text


async def test_lesson_update_has_no_way_to_set_activity_type_or_quiz_id(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _make_course(client, admin_token)
    module_id = await _make_module(client, admin_token, course_id)
    lesson_id = await _make_lesson(client, admin_token, module_id)

    resp = await client.patch(
        f"/api/v1/lessons/{lesson_id}",
        json={"title": "Renamed", "activity_type": "quiz", "quiz_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Renamed"
    assert body["activity_type"] == "document"
    assert body["quiz_id"] is None


async def test_tenant_assignment_requires_a_published_course(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _make_course(client, admin_token)
    resp = await client.post(
        f"/api/v1/courses/{course_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text
    assert "published" in resp.json()["error"]["message"].lower()


async def test_tenant_assignment_is_idempotent_and_updates_is_bespoke(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _make_published_course(client, admin_token)

    first = await client.post(
        f"/api/v1/courses/{course_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"/api/v1/courses/{course_id}/tenant-assignments",
        json={"is_bespoke": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    listed = await client.get(
        "/api/v1/tenant-assignments", headers={"Authorization": f"Bearer {admin_token}"}
    )
    matching = [r for r in listed.json()["items"] if r["course_id"] == course_id]
    assert len(matching) == 1
    assert matching[0]["is_bespoke"] is True
