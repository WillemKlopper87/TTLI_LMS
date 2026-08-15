"""Free-preview lessons (`Lesson.access_level="public"`): the public
curriculum/preview surface, and that every activity type's real learner
endpoint honours the same public-or-enrolled rule consistently
(services/enrolment.py's own docstring on why this had to be uniform,
not just added to the video path).
"""

from __future__ import annotations

import asyncio
import shutil
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


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


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
    return f"preview-{uuid.uuid4().hex[:12]}@example.com"


def _unique_title() -> str:
    return f"Preview Test Course {uuid.uuid4().hex[:8]}"


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
    assert resp.status_code == 200
    return str(resp.json()["access_token"]), user_id


async def _make_course_with_lessons(
    client, token: str, *, public_body: str = "Free preview content."
) -> tuple[str, str, str]:
    """One published, tenant-assigned course with two lessons: a public
    preview document lesson and a paid (default) one — returns
    (course_id, public_lesson_id, paid_lesson_id)."""
    course = await client.post(
        "/api/v1/courses",
        json={"title": _unique_title()},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]
    module = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        json={"title": "Module 1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert module.status_code == 201, module.text
    module_id = module.json()["id"]

    public_lesson = await client.post(
        f"/api/v1/modules/{module_id}/lessons",
        json={"title": "Free Preview", "access_level": "public", "body": public_body},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert public_lesson.status_code == 201, public_lesson.text

    paid_lesson = await client.post(
        f"/api/v1/modules/{module_id}/lessons",
        json={"title": "Paid Lesson", "body": "Members only."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert paid_lesson.status_code == 201, paid_lesson.text

    published = await client.post(
        f"/api/v1/courses/{course_id}/publish", headers={"Authorization": f"Bearer {token}"}
    )
    assert published.status_code == 200, published.text
    assigned = await client.post(
        f"/api/v1/courses/{course_id}/tenant-assignments",
        json={"is_bespoke": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert assigned.status_code == 201, assigned.text
    return course_id, public_lesson.json()["id"], paid_lesson.json()["id"]


async def test_public_curriculum_requires_no_auth_and_shows_access_level(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    course_id, public_lesson_id, paid_lesson_id = await _make_course_with_lessons(
        client, author_token
    )

    resp = await client.get(f"/api/v1/public/courses/{course_id}/curriculum")
    assert resp.status_code == 200, resp.text
    lessons = {lesson["id"]: lesson for m in resp.json()["modules"] for lesson in m["lessons"]}
    assert lessons[public_lesson_id]["access_level"] == "public"
    assert lessons[paid_lesson_id]["access_level"] == "paid"
    # No body/quiz/survey/assignment/video FKs — shape only.
    assert "body" not in lessons[public_lesson_id]


async def test_public_curriculum_hides_unpublished_courses(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    course = await client.post(
        "/api/v1/courses",
        json={"title": _unique_title()},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    course_id = course.json()["id"]

    resp = await client.get(f"/api/v1/public/courses/{course_id}/curriculum")
    assert resp.status_code == 404


async def test_public_lesson_preview_403s_for_non_public_lesson(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _course_id, _public_id, paid_lesson_id = await _make_course_with_lessons(client, author_token)

    resp = await client.get(f"/api/v1/public/lessons/{paid_lesson_id}/preview")
    assert resp.status_code == 404


async def test_public_lesson_preview_returns_body_for_document_lesson(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _course_id, public_lesson_id, _paid_id = await _make_course_with_lessons(
        client, author_token, public_body="Come see the full course!"
    )

    resp = await client.get(f"/api/v1/public/lessons/{public_lesson_id}/preview")
    assert resp.status_code == 200, resp.text
    assert resp.json()["body"] == "Come see the full course!"


async def test_start_lesson_still_requires_enrolment_even_for_public_lesson(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Preview is view-only — it never touches completion.py, per
    services/enrolment.py's own scope decision."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _course_id, public_lesson_id, _paid_id = await _make_course_with_lessons(client, author_token)

    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.post(
        f"/api/v1/lessons/{public_lesson_id}/start",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert resp.status_code == 403


async def test_quiz_preview_omits_correct_answers_and_creates_no_attempt(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _course_id, public_lesson_id, _paid_id = await _make_course_with_lessons(client, author_token)

    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Preview Quiz", "pass_score": 70, "max_attempts": 2},
    )
    quiz_id = quiz.json()["id"]
    await client.post(
        f"/api/v1/quizzes/{quiz_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "question_type": "single_choice",
            "prompt": "2 + 2?",
            "options": [
                {"id": "a", "text": "3", "correct": False},
                {"id": "b", "text": "4", "correct": True},
            ],
            "position": 1,
            "points": 1,
        },
    )
    await client.post(
        f"/api/v1/lessons/{public_lesson_id}/quiz?quiz_id={quiz_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    preview = await client.get(
        f"/api/v1/quizzes/{quiz_id}/preview", headers={"Authorization": f"Bearer {stranger_token}"}
    )
    assert preview.status_code == 200, preview.text
    assert all("correct" not in opt for opt in preview.json()["questions"][0]["options"])

    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM quiz_attempts WHERE quiz_id = :q"), {"q": quiz_id}
            )
        ).scalar_one()
    assert count == 0


async def test_survey_view_allows_public_lesson_without_enrolment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _course_id, public_lesson_id, _paid_id = await _make_course_with_lessons(client, author_token)

    survey = await client.post(
        "/api/v1/surveys",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Preview Survey", "response_mode": "identified", "minimum_group_size": 1},
    )
    survey_id = survey.json()["id"]
    await client.post(
        f"/api/v1/lessons/{public_lesson_id}/survey?survey_id={survey_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.get(
        f"/api/v1/surveys/{survey_id}", headers={"Authorization": f"Bearer {stranger_token}"}
    )
    assert resp.status_code == 200, resp.text


async def test_assignment_preview_allows_public_lesson_without_enrolment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _course_id, public_lesson_id, _paid_id = await _make_course_with_lessons(client, author_token)

    assignment = await client.post(
        "/api/v1/assignments",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "title": "Preview Essay",
            "instructions": "Write something.",
            "approval_required": True,
        },
    )
    assignment_id = assignment.json()["id"]
    await client.post(
        f"/api/v1/lessons/{public_lesson_id}/assignment?assignment_id={assignment_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.get(
        f"/api/v1/assignments/{assignment_id}/preview",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["instructions"] == "Write something."


async def test_video_playback_succeeds_for_public_lesson_without_enrolment(
    client, tenant_session_factory, crypto, tmp_path_factory
) -> None:  # type: ignore[no-untyped-def]
    if not _ffmpeg_available():
        pytest.skip("no ffmpeg/ffprobe on PATH")
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _course_id, public_lesson_id, paid_lesson_id = await _make_course_with_lessons(
        client, author_token
    )

    out_dir = tmp_path_factory.mktemp("preview-media")
    source = out_dir / "source.mp4"

    async def _generate() -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-t",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(source),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    await _generate()
    assert source.exists()

    upload = await client.post(
        "/api/v1/video-assets",
        headers={"Authorization": f"Bearer {author_token}"},
        files={"file": ("source.mp4", source.read_bytes(), "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    asset_id = upload.json()["id"]

    from src.core.config import get_settings
    from src.core.db import get_sessionmaker
    from src.services.media.pipeline import transcode_video_asset
    from src.services.storage import get_storage_adapter

    settings = get_settings()
    storage = get_storage_adapter(settings)
    factory = get_sessionmaker()
    async with factory() as s:
        await transcode_video_asset(s, storage, settings, video_asset_id=uuid.UUID(asset_id))

    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    # Attached only to the paid lesson first — a stranger with no
    # entitlement must not be able to play it.
    attach_paid = await client.post(
        f"/api/v1/lessons/{paid_lesson_id}/video?video_asset_id={asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert attach_paid.status_code == 204, attach_paid.text
    denied = await client.get(
        f"/api/v1/media/{asset_id}/playback", headers={"Authorization": f"Bearer {stranger_token}"}
    )
    assert denied.status_code == 403

    # The same asset also attached to the public preview lesson — now it
    # must play, since has_access_to_video treats "any matching lesson is
    # public" as sufficient (services/enrolment.py's own docstring).
    attach_public = await client.post(
        f"/api/v1/lessons/{public_lesson_id}/video?video_asset_id={asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert attach_public.status_code == 204, attach_public.text
    allowed = await client.get(
        f"/api/v1/media/{asset_id}/playback", headers={"Authorization": f"Bearer {stranger_token}"}
    )
    assert allowed.status_code == 200, allowed.text
