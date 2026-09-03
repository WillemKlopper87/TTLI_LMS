"""H-12 (fable5.1_review.md): the cross-tenant content-authoring boundary.

`Course`/`Module`/`Lesson`/`LessonBlock`/`Quiz`/`Survey`/`Assignment`/
`VideoAsset`/`AudioAsset`/`CertificateTemplate`/`BadgeTemplate`/
`LearningPath` are global rows (no `tenant_id`) — `CourseTenantAssignment`
/`LearningPathTenantAssignment` are the only things that ever make one
visible to a particular tenant. Before this fix, every authoring
read/write in `routers/courses.py`, `course_wizard.py`, `assessment.py`,
`media.py`, `credentials.py` and `learning_paths.py` authorised purely on
the `course:edit`/`course:publish`/`course:view` permission strings, which
the seeded tenant `admin` role holds unconditionally — so any tenant's
admin could read, edit and publish another tenant's bespoke course, quiz
answer keys included.

Two real tenants (`demo` at `localhost`, `acme` at `meridian.localhost`,
both seeded by `0002`/`0011`) stand in for "us" and "the attacker" —
`_login` always sends the `X-Tenant-Host` matching the token's own tenant
(`core/deps.py::get_principal` asserts host and JWT tenant match, so a
cross-tenant probe is always issued *as* the attacking tenant's own
admin, never by spoofing the header alone). `_build_bespoke_rig` has
`demo`'s admin author a full course (module, lesson, quiz/survey/
assignment blocks, a video asset, cert + badge templates, a learning
path) and mark the course/path bespoke to itself; every test below then
acts as `acme`'s admin against those ids.
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
    return f"h12-{slug}-{uuid.uuid4().hex[:12]}@example.com"


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


class _Rig:
    """Every id `demo`'s admin creates, and the token to act as `demo`."""

    def __init__(self) -> None:
        self.admin_token: str = ""
        self.course_id: str = ""
        self.module_id: str = ""
        self.lesson_id: str = ""
        self.quiz_id: str = ""
        self.survey_id: str = ""
        self.assignment_id: str = ""
        self.video_asset_id: str = ""
        self.cert_template_id: str = ""
        self.badge_template_id: str = ""
        self.path_id: str = ""


async def _build_bespoke_rig(client, tenant_session_factory, crypto, *, demo_id: uuid.UUID) -> _Rig:
    rig = _Rig()
    rig.admin_token = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role="admin"
    )
    h = _auth(rig.admin_token, "demo")

    course = await client.post(
        "/api/v1/courses", json={"title": f"H12 Bespoke {uuid.uuid4().hex[:8]}"}, headers=h
    )
    assert course.status_code == 201, course.text
    rig.course_id = course.json()["id"]

    module = await client.post(
        f"/api/v1/courses/{rig.course_id}/modules", json={"title": "Module 1"}, headers=h
    )
    assert module.status_code == 201, module.text
    rig.module_id = module.json()["id"]

    lesson = await client.post(
        f"/api/v1/modules/{rig.module_id}/lessons", json={"title": "Lesson 1"}, headers=h
    )
    assert lesson.status_code == 201, lesson.text
    rig.lesson_id = lesson.json()["id"]

    # Quiz, with a real answer key — the sharpest thing H-12 exposed.
    quiz = await client.post(
        "/api/v1/quizzes",
        json={"title": "Bespoke Quiz", "pass_score": 70, "max_attempts": 2},
        headers=h,
    )
    assert quiz.status_code == 201, quiz.text
    rig.quiz_id = quiz.json()["id"]
    question = await client.post(
        f"/api/v1/quizzes/{rig.quiz_id}/questions",
        json={
            "question_type": "single_choice",
            "prompt": "The secret answer is?",
            "options": [
                {"id": "a", "text": "wrong", "correct": False},
                {"id": "b", "text": "correct", "correct": True},
            ],
            "position": 0,
            "points": 1,
        },
        headers=h,
    )
    assert question.status_code == 204, question.text
    quiz_block = await client.post(
        f"/api/v1/lessons/{rig.lesson_id}/blocks", json={"block_type": "quiz"}, headers=h
    )
    assert quiz_block.status_code == 201, quiz_block.text
    attach_quiz = await client.post(
        f"/api/v1/lessons/{rig.lesson_id}/blocks/{quiz_block.json()['id']}/quiz"
        f"?quiz_id={rig.quiz_id}",
        headers=h,
    )
    assert attach_quiz.status_code == 204, attach_quiz.text

    survey = await client.post(
        "/api/v1/surveys",
        json={"title": "Bespoke Survey", "response_mode": "identified", "minimum_group_size": 1},
        headers=h,
    )
    assert survey.status_code == 201, survey.text
    rig.survey_id = survey.json()["id"]
    survey_block = await client.post(
        f"/api/v1/lessons/{rig.lesson_id}/blocks", json={"block_type": "survey"}, headers=h
    )
    assert survey_block.status_code == 201, survey_block.text
    attach_survey = await client.post(
        f"/api/v1/lessons/{rig.lesson_id}/blocks/{survey_block.json()['id']}/survey"
        f"?survey_id={rig.survey_id}",
        headers=h,
    )
    assert attach_survey.status_code == 204, attach_survey.text

    assignment = await client.post(
        "/api/v1/assignments", json={"title": "Bespoke Assignment"}, headers=h
    )
    assert assignment.status_code == 201, assignment.text
    rig.assignment_id = assignment.json()["id"]
    assignment_block = await client.post(
        f"/api/v1/lessons/{rig.lesson_id}/blocks", json={"block_type": "assignment"}, headers=h
    )
    assert assignment_block.status_code == 201, assignment_block.text
    attach_assignment = await client.post(
        f"/api/v1/lessons/{rig.lesson_id}/blocks/{assignment_block.json()['id']}/assignment"
        f"?assignment_id={rig.assignment_id}",
        headers=h,
    )
    assert attach_assignment.status_code == 204, attach_assignment.text

    # A video asset, inserted directly (bypassing upload/antivirus/ffmpeg,
    # none of which this boundary test needs) and bound to the course —
    # same shape `attach_video_to_block` leaves behind for a real upload.
    video_id = uuid.uuid4()
    async with tenant_session_factory(demo_id) as s:
        s.add(
            VideoAsset(
                id=video_id,
                source_object_key="h12/fixture.mp4",
                state="ready",
                delivery_mode="progressive",
                course_id=uuid.UUID(rig.course_id),
            )
        )
    rig.video_asset_id = str(video_id)

    cert = await client.post(
        "/api/v1/certificate-templates",
        json={
            "title": "Bespoke Certificate",
            "issuer_name": "Demo Co",
            "signatory_name": "Jane Doe",
            "signatory_title": "Dean",
        },
        headers=h,
    )
    assert cert.status_code == 201, cert.text
    rig.cert_template_id = cert.json()["id"]

    badge = await client.post(
        "/api/v1/badge-templates",
        json={"title": "Bespoke Badge", "criteria": "Finish it", "issuer_name": "Demo Co"},
        headers=h,
    )
    assert badge.status_code == 201, badge.text
    rig.badge_template_id = badge.json()["id"]

    link = await client.patch(
        f"/api/v1/courses/{rig.course_id}",
        json={
            "certificate_template_id": rig.cert_template_id,
            "badge_template_id": rig.badge_template_id,
        },
        headers=h,
    )
    assert link.status_code == 200, link.text

    published = await client.post(f"/api/v1/courses/{rig.course_id}/publish", headers=h)
    assert published.status_code == 200, published.text

    assigned = await client.post(
        f"/api/v1/courses/{rig.course_id}/tenant-assignments",
        json={"is_bespoke": True},
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text

    # A second, unrelated published course -- publish_learning_path
    # requires >= 2 published member courses; only the first needs to be
    # the bespoke fixture under test.
    filler_course = await client.post(
        "/api/v1/courses", json={"title": f"H12 Filler {uuid.uuid4().hex[:8]}"}, headers=h
    )
    assert filler_course.status_code == 201, filler_course.text
    filler_course_id = filler_course.json()["id"]
    filler_module = await client.post(
        f"/api/v1/courses/{filler_course_id}/modules", json={"title": "M"}, headers=h
    )
    assert filler_module.status_code == 201, filler_module.text
    filler_lesson = await client.post(
        f"/api/v1/modules/{filler_module.json()['id']}/lessons", json={"title": "L"}, headers=h
    )
    assert filler_lesson.status_code == 201, filler_lesson.text
    filler_published = await client.post(f"/api/v1/courses/{filler_course_id}/publish", headers=h)
    assert filler_published.status_code == 200, filler_published.text

    # A learning path bundling the bespoke course, published and marked
    # bespoke to demo -- otherwise the path itself stays "draft" (still
    # unclaimed, so it *should* stay open, per the same rule courses
    # follow) and wouldn't actually exercise this boundary.
    path = await client.post(
        "/api/v1/learning-paths", json={"title": f"H12 Path {uuid.uuid4().hex[:8]}"}, headers=h
    )
    assert path.status_code == 201, path.text
    rig.path_id = path.json()["id"]
    added = await client.post(
        f"/api/v1/learning-paths/{rig.path_id}/courses",
        json={"course_id": rig.course_id},
        headers=h,
    )
    assert added.status_code == 201, added.text
    added_filler = await client.post(
        f"/api/v1/learning-paths/{rig.path_id}/courses",
        json={"course_id": filler_course_id},
        headers=h,
    )
    assert added_filler.status_code == 201, added_filler.text
    path_published = await client.post(f"/api/v1/learning-paths/{rig.path_id}/publish", headers=h)
    assert path_published.status_code == 200, path_published.text
    path_assigned = await client.post(
        f"/api/v1/learning-paths/{rig.path_id}/tenant-assignments",
        json={"is_bespoke": True},
        headers=h,
    )
    assert path_assigned.status_code == 201, path_assigned.text

    return rig


def _assert_not_found(resp) -> None:  # type: ignore[no-untyped-def]
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


# ============================================================ Courses ===


async def test_course_read_and_write_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The concrete H-12 reproduction: a course assigned only to `demo`,
    called by `acme`'s admin — GET, PATCH and publish/unpublish must all
    read as if the course doesn't exist."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    _assert_not_found(await client.get(f"/api/v1/courses/{rig.course_id}", headers=h))
    _assert_not_found(
        await client.patch(
            f"/api/v1/courses/{rig.course_id}", json={"title": "Hijacked"}, headers=h
        )
    )
    _assert_not_found(await client.post(f"/api/v1/courses/{rig.course_id}/publish", headers=h))
    _assert_not_found(await client.post(f"/api/v1/courses/{rig.course_id}/unpublish", headers=h))
    _assert_not_found(
        await client.patch(
            f"/api/v1/courses/{rig.course_id}/manager-visibility",
            json={"manager_visibility": "individual_enabled"},
            headers=h,
        )
    )
    _assert_not_found(
        await client.patch(
            f"/api/v1/courses/{rig.course_id}/video-settings",
            json={"allow_bypass": False},
            headers=h,
        )
    )


async def test_course_list_excludes_another_tenants_bespoke_course(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    listed = await client.get("/api/v1/courses", headers=_auth(acme_admin, "acme"))
    assert listed.status_code == 200, listed.text
    assert rig.course_id not in {c["id"] for c in listed.json()["items"]}


async def test_module_lesson_write_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    _assert_not_found(
        await client.get(f"/api/v1/courses/{rig.course_id}/modules", headers=h)
    )
    _assert_not_found(
        await client.post(
            f"/api/v1/courses/{rig.course_id}/modules", json={"title": "Injected"}, headers=h
        )
    )
    _assert_not_found(
        await client.patch(
            f"/api/v1/modules/{rig.module_id}", json={"title": "Hijacked module"}, headers=h
        )
    )
    _assert_not_found(
        await client.get(f"/api/v1/modules/{rig.module_id}/lessons", headers=h)
    )
    _assert_not_found(
        await client.post(
            f"/api/v1/modules/{rig.module_id}/lessons", json={"title": "Injected"}, headers=h
        )
    )
    _assert_not_found(
        await client.patch(
            f"/api/v1/lessons/{rig.lesson_id}", json={"title": "Hijacked lesson"}, headers=h
        )
    )
    _assert_not_found(await client.get(f"/api/v1/lessons/{rig.lesson_id}", headers=h))


async def test_lesson_block_write_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    _assert_not_found(
        await client.post(
            f"/api/v1/lessons/{rig.lesson_id}/blocks", json={"block_type": "text"}, headers=h
        )
    )
    _assert_not_found(
        await client.post(
            f"/api/v1/lessons/{rig.lesson_id}/blocks/reorder",
            json={"ordered_ids": [str(uuid.uuid4())]},
            headers=h,
        )
    )
    _assert_not_found(
        await client.delete(f"/api/v1/modules/{rig.module_id}", headers=h)
    )
    _assert_not_found(
        await client.delete(f"/api/v1/lessons/{rig.lesson_id}", headers=h)
    )


# NOTE on a related but unfixed vector: `POST /courses/{id}/tenant-
# assignments` (`assign_course_to_tenant`) does not refuse `acme` self-
# assigning onto a course already bespoke to `demo`. `course_tenant_
# assignments` carries FORCE ROW LEVEL SECURITY, so no query issued
# inside `acme`'s request transaction can ever see `demo`'s row to
# refuse it against — see that function's own docstring. The read/write
# boundary this file otherwise tests holds regardless (a course_id
# `acme` was never handed cannot be discovered through any listing this
# fix touches), so exploiting this residual gap needs the id already
# known out of band; closing it fully needs either a SECURITY DEFINER
# cross-tenant existence check or moving assignment off self-service.


# ============================================================== Quiz ===


async def test_quiz_answer_key_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The single sharpest claim in H-12: GET /quizzes/{id} must not hand
    over another tenant's answer key."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    _assert_not_found(
        await client.get(f"/api/v1/quizzes/{rig.quiz_id}", headers=_auth(acme_admin, "acme"))
    )


async def test_quiz_list_excludes_another_tenants_quiz(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    listed = await client.get("/api/v1/quizzes", headers=_auth(acme_admin, "acme"))
    assert listed.status_code == 200, listed.text
    assert rig.quiz_id not in {q["id"] for q in listed.json()["items"]}


async def test_quiz_question_write_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    resp = await client.post(
        f"/api/v1/quizzes/{rig.quiz_id}/questions",
        json={
            "question_type": "single_choice",
            "prompt": "injected",
            "options": [
                {"id": "a", "text": "x", "correct": True},
                {"id": "b", "text": "y", "correct": False},
            ],
            "position": 1,
            "points": 1,
        },
        headers=_auth(acme_admin, "acme"),
    )
    _assert_not_found(resp)


async def test_attach_cannot_launder_read_access_to_another_tenants_quiz(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """If `acme` could attach `demo`'s bespoke quiz to a block in its own
    new course, `course_ids_for_quiz` would then include an `acme`-owned
    course too and `GET /quizzes/{id}`'s "any referencing course" rule
    would treat the quiz as shared with `acme` — laundering read access
    to the answer key. The attach itself must be refused."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    own_course = await client.post(
        "/api/v1/courses", json={"title": f"Acme own {uuid.uuid4().hex[:8]}"}, headers=h
    )
    assert own_course.status_code == 201, own_course.text
    own_module = await client.post(
        f"/api/v1/courses/{own_course.json()['id']}/modules", json={"title": "M"}, headers=h
    )
    assert own_module.status_code == 201, own_module.text
    own_lesson = await client.post(
        f"/api/v1/modules/{own_module.json()['id']}/lessons", json={"title": "L"}, headers=h
    )
    assert own_lesson.status_code == 201, own_lesson.text
    own_block = await client.post(
        f"/api/v1/lessons/{own_lesson.json()['id']}/blocks", json={"block_type": "quiz"}, headers=h
    )
    assert own_block.status_code == 201, own_block.text

    attach = await client.post(
        f"/api/v1/lessons/{own_lesson.json()['id']}/blocks/{own_block.json()['id']}/quiz"
        f"?quiz_id={rig.quiz_id}",
        headers=h,
    )
    _assert_not_found(attach)

    # And the laundering attempt must not have granted read access either.
    _assert_not_found(await client.get(f"/api/v1/quizzes/{rig.quiz_id}", headers=h))


# ============================================================ Surveys ===


async def test_survey_read_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")
    _assert_not_found(await client.get(f"/api/v1/surveys/{rig.survey_id}", headers=h))
    _assert_not_found(await client.get(f"/api/v1/surveys/{rig.survey_id}/results", headers=h))


# ========================================================= Assignments ===


async def test_assignment_read_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    _assert_not_found(
        await client.get(
            f"/api/v1/assignments/{rig.assignment_id}", headers=_auth(acme_admin, "acme")
        )
    )


# ============================================================== Media ===


async def test_video_asset_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    _assert_not_found(await client.get(f"/api/v1/video-assets/{rig.video_asset_id}", headers=h))
    listed = await client.get("/api/v1/video-assets", headers=h)
    assert listed.status_code == 200, listed.text
    assert rig.video_asset_id not in {v["id"] for v in listed.json()["items"]}


# ========================================================= Credentials ===


async def test_certificate_and_badge_template_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    cert_list = await client.get("/api/v1/certificate-templates", headers=h)
    assert cert_list.status_code == 200, cert_list.text
    assert rig.cert_template_id not in {t["id"] for t in cert_list.json()["items"]}

    badge_list = await client.get("/api/v1/badge-templates", headers=h)
    assert badge_list.status_code == 200, badge_list.text
    assert rig.badge_template_id not in {t["id"] for t in badge_list.json()["items"]}

    _assert_not_found(
        await client.patch(
            f"/api/v1/certificate-templates/{rig.cert_template_id}",
            json={"title": "Hijacked"},
            headers=h,
        )
    )
    _assert_not_found(
        await client.patch(
            f"/api/v1/badge-templates/{rig.badge_template_id}",
            json={"title": "Hijacked"},
            headers=h,
        )
    )


# ====================================================== Learning paths ===


async def test_learning_path_denied_across_tenant(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    _assert_not_found(await client.get(f"/api/v1/learning-paths/{rig.path_id}", headers=h))
    _assert_not_found(
        await client.patch(
            f"/api/v1/learning-paths/{rig.path_id}", json={"title": "Hijacked"}, headers=h
        )
    )
    _assert_not_found(
        await client.get(f"/api/v1/learning-paths/{rig.path_id}/courses", headers=h)
    )

    listed = await client.get("/api/v1/learning-paths", headers=h)
    assert listed.status_code == 200, listed.text
    assert rig.path_id not in {p["id"] for p in listed.json()["items"]}


async def test_learning_path_cannot_bundle_another_tenants_bespoke_course(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Bundling a foreign bespoke course into your own path would surface
    its title/summary on that path's own public listing — the course
    being added must be one this tenant can already see too."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    rig = await _build_bespoke_rig(client, tenant_session_factory, crypto, demo_id=demo_id)
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    h = _auth(acme_admin, "acme")

    own_path = await client.post(
        "/api/v1/learning-paths", json={"title": f"Acme path {uuid.uuid4().hex[:8]}"}, headers=h
    )
    assert own_path.status_code == 201, own_path.text
    resp = await client.post(
        f"/api/v1/learning-paths/{own_path.json()['id']}/courses",
        json={"course_id": rig.course_id},
        headers=h,
    )
    _assert_not_found(resp)


# ===================================================== Positive controls ===


async def test_shared_catalogue_course_remains_visible_to_both_tenants(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The demo seed data (0011) assigns the platform's one seeded course
    to *both* `demo` and `acme`, `is_bespoke=False` — the genuinely
    shared-catalogue case H-12's fix must not break."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    async with tenant_session_factory(None) as s:
        shared_course_id = (
            await s.execute(
                sa.text("SELECT id FROM courses WHERE slug = 'executive-leadership-certificate'")
            )
        ).scalar_one()

    demo_admin = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role="admin"
    )
    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )

    demo_get = await client.get(
        f"/api/v1/courses/{shared_course_id}", headers=_auth(demo_admin, "demo")
    )
    acme_get = await client.get(
        f"/api/v1/courses/{shared_course_id}", headers=_auth(acme_admin, "acme")
    )
    assert demo_get.status_code == 200, demo_get.text
    assert acme_get.status_code == 200, acme_get.text
    assert demo_get.json()["id"] == acme_get.json()["id"] == str(shared_course_id)


async def test_creating_tenant_keeps_access_before_publish_and_assignment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The create -> module -> lesson -> publish -> assign lifecycle
    (already covered end-to-end by `test_courses.py`) has no
    `CourseTenantAssignment` row until its very last step — the
    authoring tenant must still be able to work on its own course
    through that whole window. `Course.created_by_tenant_id` (0042) is
    what makes that possible without also reopening the course to every
    *other* tenant during the same window (the next test) — see
    `services/courses.py::course_authorable`'s docstring for why a
    weaker "draft = open to anyone" rule can't make both true at once
    under `course_tenant_assignments`' row-level security."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    demo_admin = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role="admin"
    )
    course = await client.post(
        "/api/v1/courses",
        json={"title": f"Unclaimed {uuid.uuid4().hex[:8]}"},
        headers=_auth(demo_admin, "demo"),
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]

    # Publish (no assignment yet -- the exact gap `created_by_tenant_id`
    # exists to cover) then read again, still as the creating tenant.
    module = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        json={"title": "M"},
        headers=_auth(demo_admin, "demo"),
    )
    assert module.status_code == 201, module.text
    lesson = await client.post(
        f"/api/v1/modules/{module.json()['id']}/lessons",
        json={"title": "L"},
        headers=_auth(demo_admin, "demo"),
    )
    assert lesson.status_code == 201, lesson.text
    published = await client.post(
        f"/api/v1/courses/{course_id}/publish", headers=_auth(demo_admin, "demo")
    )
    assert published.status_code == 200, published.text

    still_own = await client.get(f"/api/v1/courses/{course_id}", headers=_auth(demo_admin, "demo"))
    assert still_own.status_code == 200, still_own.text


async def test_other_tenant_cannot_see_a_freshly_created_unassigned_course(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The tighter half of the same story: a course belongs to the
    tenant that authored it from the moment it's created, not to
    whichever tenant happens to ask first — `acme` gets no free look at
    `demo`'s course just because it hasn't been assigned to anyone yet."""
    demo_id = await _tenant_id(tenant_session_factory, "demo")
    acme_id = await _tenant_id(tenant_session_factory, "acme")
    demo_admin = await _login(
        client, tenant_session_factory, crypto, slug="demo", tenant_id=demo_id, role="admin"
    )
    course = await client.post(
        "/api/v1/courses",
        json={"title": f"Unclaimed {uuid.uuid4().hex[:8]}"},
        headers=_auth(demo_admin, "demo"),
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]

    acme_admin = await _login(
        client, tenant_session_factory, crypto, slug="acme", tenant_id=acme_id, role="admin"
    )
    _assert_not_found(
        await client.get(f"/api/v1/courses/{course_id}", headers=_auth(acme_admin, "acme"))
    )
