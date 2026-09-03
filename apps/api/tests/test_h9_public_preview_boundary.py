"""H-9 (fable5.1_review.md): public-preview media/quiz access ignoring
course state and tenant assignment.

`services/enrolment.py::_has_access_to_media`/`_has_view_access_via_
lesson_fk` used to grant access the instant *any* lesson block
referencing a video/quiz/survey/assignment sat in a `access_level=
"public"` lesson — no `Course.state == "published"` check, no
`CourseTenantAssignment` predicate. A signed-in user of any tenant could
therefore mint a playback URL, or view a quiz preview, for a draft
course or one bespoke to a different tenant, as long as some lesson
happened to be marked public. The fix mirrors `services/courses.py::
get_public_lesson_preview`'s already-correct visibility rule: published,
and the caller's own tenant actually holds a `CourseTenantAssignment`.

Two real seeded tenants (`demo` at `localhost`, `acme` at
`meridian.localhost`, both from `0002`/`0011`) stand in for "the
authoring tenant" and "an unrelated tenant" — the same fixture shape
`test_h12_tenant_boundary.py` uses for the sibling authoring-boundary
finding. Every probe below is a *plain* learner (`role=None`) — not an
author/admin — to isolate this preview-access boundary from H-12's
separate `course:edit`/`course_authorable` authoring boundary, which
some of these same endpoints also happen to enforce on an authoring
caller.
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
from src.models.media import VideoAsset
from src.models.rbac import RoleAssignment
from src.services import identity

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery staple 9!"
TENANT_HOSTS = {"demo": "localhost", "acme": "meridian.localhost"}


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
        yield c
    await dispose_engine()
    await dispose_redis()
    await dispose_queue()


def _unique_email(slug: str) -> str:
    return f"h9-{slug}-{uuid.uuid4().hex[:12]}@example.com"


async def _tenant_id(tenant_session_factory, slug: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug})
        ).first()
    assert row is not None, f"tenant {slug!r} is not seeded"
    return uuid.UUID(str(row[0]))


async def _login(
    client, tenant_session_factory, crypto, *, slug: str, tenant_id: uuid.UUID, role: str | None
) -> str:  # type: ignore[no-untyped-def]
    email = _unique_email(slug)
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role))
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"X-Tenant-Host": TENANT_HOSTS[slug]},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def _auth(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-Host": TENANT_HOSTS[slug]}


async def _author_public_lesson_with_video_and_quiz(
    client, tenant_session_factory, crypto, *, demo_id: uuid.UUID
) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """`demo`'s content author builds one course with a single
    `access_level="public"` lesson carrying both a video block (asset
    inserted directly — the same bypass-upload shortcut
    `test_h12_tenant_boundary.py::_build_bespoke_rig` uses, this
    boundary needs no real transcode) and a quiz block. Left in `draft`
    state — publishing/assigning is each test's own call, since which
    state the course is left in is exactly what each test varies."""
    author_token = await _login(
        client,
        tenant_session_factory,
        crypto,
        slug="demo",
        tenant_id=demo_id,
        role="content_author",
    )
    h = _auth(author_token, "demo")

    course = await client.post(
        "/api/v1/courses", json={"title": f"H9 Public Preview {uuid.uuid4().hex[:8]}"}, headers=h
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]

    module = await client.post(
        f"/api/v1/courses/{course_id}/modules", json={"title": "Module 1"}, headers=h
    )
    assert module.status_code == 201, module.text
    module_id = module.json()["id"]

    lesson = await client.post(
        f"/api/v1/modules/{module_id}/lessons",
        json={"title": "Free Sample", "access_level": "public"},
        headers=h,
    )
    assert lesson.status_code == 201, lesson.text
    lesson_id = lesson.json()["id"]

    video_id = uuid.uuid4()
    async with tenant_session_factory(demo_id) as s:
        s.add(
            VideoAsset(
                id=video_id,
                source_object_key="h9/fixture.mp4",
                state="ready",
                delivery_mode="progressive",
                course_id=uuid.UUID(course_id),
            )
        )
    video_block = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks", json={"block_type": "video"}, headers=h
    )
    assert video_block.status_code == 201, video_block.text
    attach_video = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{video_block.json()['id']}/video"
        f"?video_asset_id={video_id}",
        headers=h,
    )
    assert attach_video.status_code == 204, attach_video.text

    quiz = await client.post(
        "/api/v1/quizzes",
        json={"title": "Free Sample Quiz", "pass_score": 70, "max_attempts": 2},
        headers=h,
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["id"]
    quiz_block = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks", json={"block_type": "quiz"}, headers=h
    )
    assert quiz_block.status_code == 201, quiz_block.text
    attach_quiz = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{quiz_block.json()['id']}/quiz?quiz_id={quiz_id}",
        headers=h,
    )
    assert attach_quiz.status_code == 204, attach_quiz.text

    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "video_asset_id": str(video_id),
        "quiz_id": quiz_id,
        "author_token": author_token,
    }


async def _publish_and_assign(client, *, course_id: str, auth: dict[str, str]) -> None:
    published = await client.post(f"/api/v1/courses/{course_id}/publish", headers=auth)
    assert published.status_code == 200, published.text
    assigned = await client.post(
        f"/api/v1/courses/{course_id}/tenant-assignments",
        json={"is_bespoke": True},
        headers=auth,
    )
    assert assigned.status_code == 201, assigned.text


async def test_public_lesson_video_playback_refused_for_a_draft_course(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """A `public`-access lesson in a course still in `draft` must not
    grant playback — `access_level` alone used to be sufficient."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    rig = await _author_public_lesson_with_video_and_quiz(
        client, tenant_session_factory, crypto, demo_id=demo_id
    )
    learner_token = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role=None
    )

    resp = await client.get(
        f"/api/v1/media/{rig['video_asset_id']}/playback",
        headers=_auth(learner_token, "demo"),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_public_lesson_video_playback_refused_when_published_but_unassigned(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Published is not enough on its own — `services/courses.py::
    get_public_lesson_preview` requires a real `CourseTenantAssignment`
    too, and so must this equivalent check. Even `demo`'s own plain
    learner (not just a stranger tenant) must be refused here: nobody
    has been assigned this course yet, published or not."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    rig = await _author_public_lesson_with_video_and_quiz(
        client, tenant_session_factory, crypto, demo_id=demo_id
    )
    published = await client.post(
        f"/api/v1/courses/{rig['course_id']}/publish", headers=_auth(rig["author_token"], "demo")
    )
    assert published.status_code == 200, published.text

    learner_token = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role=None
    )
    resp = await client.get(
        f"/api/v1/media/{rig['video_asset_id']}/playback",
        headers=_auth(learner_token, "demo"),
    )
    assert resp.status_code == 403, resp.text


async def test_public_lesson_video_playback_refused_across_tenants(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The concrete H-9 reproduction: a course published and bespoke-
    assigned only to `demo`, probed by a plain learner of `acme` — an
    unrelated tenant must not get a playback URL just because the
    lesson happens to be `access_level="public"`."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _author_public_lesson_with_video_and_quiz(
        client, tenant_session_factory, crypto, demo_id=demo_id
    )
    await _publish_and_assign(
        client, course_id=rig["course_id"], auth=_auth(rig["author_token"], "demo")
    )

    acme_learner = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role=None
    )
    resp = await client.get(
        f"/api/v1/media/{rig['video_asset_id']}/playback",
        headers=_auth(acme_learner, "acme"),
    )
    assert resp.status_code == 403, resp.text


async def test_public_lesson_video_playback_succeeds_once_published_and_assigned(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The positive control: once the course is actually published *and*
    assigned to the caller's own tenant, a plain learner with no
    enrolment at all — the whole point of a free preview — can still
    play it. The fix must not have overtightened this."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    rig = await _author_public_lesson_with_video_and_quiz(
        client, tenant_session_factory, crypto, demo_id=demo_id
    )
    await _publish_and_assign(
        client, course_id=rig["course_id"], auth=_auth(rig["author_token"], "demo")
    )

    learner_token = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role=None
    )
    resp = await client.get(
        f"/api/v1/media/{rig['video_asset_id']}/playback",
        headers=_auth(learner_token, "demo"),
    )
    assert resp.status_code == 200, resp.text


async def test_public_lesson_quiz_preview_refused_across_tenants_allowed_within_own(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """`has_view_access_to_quiz` shares the same fix
    (`_publicly_previewable_course_ids`) via a different call site
    (`GET /quizzes/{id}/preview`) — checked independently since it is a
    genuinely separate code path (`_has_view_access_via_lesson_fk`, not
    `_has_access_to_media`)."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _author_public_lesson_with_video_and_quiz(
        client, tenant_session_factory, crypto, demo_id=demo_id
    )
    await _publish_and_assign(
        client, course_id=rig["course_id"], auth=_auth(rig["author_token"], "demo")
    )

    acme_learner = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role=None
    )
    refused = await client.get(
        f"/api/v1/quizzes/{rig['quiz_id']}/preview", headers=_auth(acme_learner, "acme")
    )
    assert refused.status_code == 403, refused.text

    demo_learner = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role=None
    )
    allowed = await client.get(
        f"/api/v1/quizzes/{rig['quiz_id']}/preview", headers=_auth(demo_learner, "demo")
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["title"] == "Free Sample Quiz"
