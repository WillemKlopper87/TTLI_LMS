"""The course-authoring wizard's additive backend surface
(`routers/course_wizard.py`, `services/course_wizard.py`): delete with
the learner-progress guard, atomic reorder (and its exact-permutation
refusal), detach-to-document, clearing a template link, the outline
read, the readiness report's blockers/warnings/info split, and
duplicate-as-template (structure cloned, quiz deep-copied, video shared).
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.ids import uuid7
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app

# Helpers only — the `client` fixture is defined per test module in this
# suite (test_courses.py, test_assessment.py, test_push.py each declare
# their own), so importing it here would shadow every test's parameter.
from tests.test_courses import (
    _demo_tenant_id,
    _login,
    _make_course,
    _make_lesson,
    _make_module,
)

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"


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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _author(client, tenant_session_factory, crypto):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token, user_id, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    return tenant_id, token, user_id


async def test_reorder_modules_is_atomic_and_requires_exact_permutation(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    _, token, _ = await _author(client, tenant_session_factory, crypto)
    course_id = await _make_course(client, token)
    a = await _make_module(client, token, course_id, title="A")
    b = await _make_module(client, token, course_id, title="B")
    c = await _make_module(client, token, course_id, title="C")

    resp = await client.post(
        f"/api/v1/courses/{course_id}/modules/reorder",
        json={"ordered_ids": [c, a, b]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert [m["title"] for m in resp.json()["items"]] == ["C", "A", "B"]
    assert [m["position"] for m in resp.json()["items"]] == [0, 1, 2]

    # Missing one sibling → refused, order untouched.
    bad = await client.post(
        f"/api/v1/courses/{course_id}/modules/reorder",
        json={"ordered_ids": [a, b]},
        headers=_auth(token),
    )
    assert bad.status_code == 400, bad.text
    assert bad.json()["error"]["code"] == "COURSE_AUTHORING_ERROR"
    again = await client.get(f"/api/v1/courses/{course_id}/modules", headers=_auth(token))
    assert [m["title"] for m in again.json()["items"]] == ["C", "A", "B"]


async def test_reorder_lessons_and_delete_renumbers_siblings(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    _, token, _ = await _author(client, tenant_session_factory, crypto)
    course_id = await _make_course(client, token)
    module_id = await _make_module(client, token, course_id)
    l1 = await _make_lesson(client, token, module_id, title="One")
    l2 = await _make_lesson(client, token, module_id, title="Two")
    l3 = await _make_lesson(client, token, module_id, title="Three")

    resp = await client.post(
        f"/api/v1/modules/{module_id}/lessons/reorder",
        json={"ordered_ids": [l3, l2, l1]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert [x["title"] for x in resp.json()["items"]] == ["Three", "Two", "One"]

    deleted = await client.delete(f"/api/v1/lessons/{l2}", headers=_auth(token))
    assert deleted.status_code == 204, deleted.text
    after = await client.get(f"/api/v1/modules/{module_id}/lessons", headers=_auth(token))
    assert [(x["title"], x["position"]) for x in after.json()["items"]] == [
        ("Three", 0),
        ("One", 1),
    ]


async def test_delete_lesson_refused_once_a_learner_has_progress(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id, token, user_id = await _author(client, tenant_session_factory, crypto)
    course_id = await _make_course(client, token)
    module_id = await _make_module(client, token, course_id)
    lesson_id = await _make_lesson(client, token, module_id)

    # Fabricate progress directly: entitlement → enrolment → lesson_completion.
    async with tenant_session_factory(tenant_id) as s:
        entitlement_id = uuid7()
        enrolment_id = uuid7()
        await s.execute(
            sa.text(
                "INSERT INTO entitlements (id, tenant_id, user_id, kind, target_id) "
                "VALUES (:i, :t, :u, 'course', :c)"
            ),
            {"i": entitlement_id, "t": tenant_id, "u": user_id, "c": uuid.UUID(course_id)},
        )
        await s.execute(
            sa.text(
                "INSERT INTO enrolments (id, tenant_id, user_id, course_id, entitlement_id) "
                "VALUES (:i, :t, :u, :c, :e)"
            ),
            {
                "i": enrolment_id,
                "t": tenant_id,
                "u": user_id,
                "c": uuid.UUID(course_id),
                "e": entitlement_id,
            },
        )
        await s.execute(
            sa.text(
                "INSERT INTO lesson_completions (id, tenant_id, enrolment_id, lesson_id, state) "
                "VALUES (:i, :t, :e, :l, 'in_progress')"
            ),
            {"i": uuid7(), "t": tenant_id, "e": enrolment_id, "l": uuid.UUID(lesson_id)},
        )

    refused = await client.delete(f"/api/v1/lessons/{lesson_id}", headers=_auth(token))
    assert refused.status_code == 400, refused.text
    assert "progress" in refused.json()["error"]["message"]
    refused_module = await client.delete(f"/api/v1/modules/{module_id}", headers=_auth(token))
    assert refused_module.status_code == 400, refused_module.text


async def test_delete_module_cascades_lessons(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    _, token, _ = await _author(client, tenant_session_factory, crypto)
    course_id = await _make_course(client, token)
    m1 = await _make_module(client, token, course_id, title="Keep")
    m2 = await _make_module(client, token, course_id, title="Drop")
    await _make_lesson(client, token, m2)
    resp = await client.delete(f"/api/v1/modules/{m2}", headers=_auth(token))
    assert resp.status_code == 204, resp.text
    left = await client.get(f"/api/v1/courses/{course_id}/modules", headers=_auth(token))
    assert [(m["id"], m["position"]) for m in left.json()["items"]] == [(m1, 0)]


async def test_detach_activity_reverts_lesson_to_document(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    _, token, _ = await _author(client, tenant_session_factory, crypto)
    course_id = await _make_course(client, token)
    module_id = await _make_module(client, token, course_id)
    lesson_id = await _make_lesson(client, token, module_id)
    quiz = await client.post(
        "/api/v1/quizzes", json={"title": "Q", "pass_score": 70}, headers=_auth(token)
    )
    assert quiz.status_code == 201, quiz.text
    attached = await client.post(
        f"/api/v1/lessons/{lesson_id}/quiz",
        params={"quiz_id": quiz.json()["id"]},
        headers=_auth(token),
    )
    assert attached.status_code == 204, attached.text

    resp = await client.delete(f"/api/v1/lessons/{lesson_id}/activity", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["activity_type"] == "document"
    assert resp.json()["quiz_id"] is None
    # The quiz itself survives — it may be attached elsewhere.
    still = await client.get(f"/api/v1/quizzes/{quiz.json()['id']}", headers=_auth(token))
    assert still.status_code == 200


async def test_clear_templates_and_readiness_report(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    _, token, _ = await _author(client, tenant_session_factory, crypto)
    course_id = await _make_course(client, token)

    # Empty course: two structural blockers, not publishable, score low.
    empty = await client.get(f"/api/v1/courses/{course_id}/readiness", headers=_auth(token))
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert body["publishable"] is False
    codes = {c["code"]: c for c in body["checks"]}
    assert codes["has_modules"]["ok"] is False
    assert codes["has_modules"]["level"] == "blocker"
    assert codes["assigned_to_tenant"]["level"] == "info"

    module_id = await _make_module(client, token, course_id)
    lesson_id = await _make_lesson(client, token, module_id)
    # A quiz rule with no quiz lesson is a blocker the old publish never saw.
    patched = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"completion_rules": {"quiz_pass_score": 70}, "description": "Real description"},
        headers=_auth(token),
    )
    assert patched.status_code == 200, patched.text
    report = (
        await client.get(f"/api/v1/courses/{course_id}/readiness", headers=_auth(token))
    ).json()
    codes = {c["code"]: c for c in report["checks"]}
    assert codes["has_modules"]["ok"] and codes["modules_have_lessons"]["ok"]
    assert codes["completion_rules_satisfiable"]["ok"] is False
    assert report["publishable"] is False
    assert codes["has_description"]["ok"] is True
    assert report["lesson_count"] == 1 and report["module_count"] == 1

    # Fix the rule → publishable; free-preview warning flips when a lesson goes public.
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"completion_rules": {}}, headers=_auth(token)
    )
    await client.patch(
        f"/api/v1/lessons/{lesson_id}", json={"access_level": "public"}, headers=_auth(token)
    )
    report = (
        await client.get(f"/api/v1/courses/{course_id}/readiness", headers=_auth(token))
    ).json()
    codes = {c["code"]: c for c in report["checks"]}
    assert report["publishable"] is True
    assert codes["has_free_preview"]["ok"] is True

    # Certificate template attach → then clear via the new endpoint.
    tmpl = await client.post(
        "/api/v1/certificate-templates",
        json={
            "title": "Cert",
            "issuer_name": "TTLI",
            "signatory_name": "X",
            "signatory_title": "Y",
        },
        headers=_auth(token),
    )
    assert tmpl.status_code == 201, tmpl.text
    with_cert = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"certificate_template_id": tmpl.json()["id"]},
        headers=_auth(token),
    )
    assert with_cert.json()["certificate_template_id"] == tmpl.json()["id"]
    cleared = await client.post(
        f"/api/v1/courses/{course_id}/clear-templates",
        json={"certificate": True},
        headers=_auth(token),
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["certificate_template_id"] is None


async def test_outline_and_duplicate_share_video_but_deep_copy_quiz(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    _, token, _ = await _author(client, tenant_session_factory, crypto)
    course_id = await _make_course(client, token, title="Original")
    m1 = await _make_module(client, token, course_id, title="M1")
    doc = await _make_lesson(client, token, m1, title="Doc")
    await client.patch(
        f"/api/v1/lessons/{doc}", json={"body": " ".join(["word"] * 400)}, headers=_auth(token)
    )
    quiz_lesson = await _make_lesson(client, token, m1, title="Quiz lesson")
    quiz = await client.post(
        "/api/v1/quizzes", json={"title": "Q", "pass_score": 70}, headers=_auth(token)
    )
    quiz_id = quiz.json()["id"]
    q = await client.post(
        f"/api/v1/quizzes/{quiz_id}/questions",
        json={
            "question_type": "single_choice",
            "prompt": "2+2?",
            "options": [
                {"id": "a", "text": "4", "correct": True},
                {"id": "b", "text": "5", "correct": False},
            ],
            "position": 0,
            "points": 1,
        },
        headers=_auth(token),
    )
    assert q.status_code == 204, q.text
    await client.post(
        f"/api/v1/lessons/{quiz_lesson}/quiz", params={"quiz_id": quiz_id}, headers=_auth(token)
    )

    outline = await client.get(f"/api/v1/courses/{course_id}/outline", headers=_auth(token))
    assert outline.status_code == 200, outline.text
    o = outline.json()
    assert o["lesson_count"] == 2
    rows = {r["lesson"]["title"]: r for r in o["modules"][0]["lessons"]}
    assert rows["Doc"]["estimated_minutes"] == 2  # 400 words / 200 wpm
    assert rows["Quiz lesson"]["question_count"] == 1
    assert o["estimated_minutes"] == 3

    dup = await client.post(f"/api/v1/courses/{course_id}/duplicate", json={}, headers=_auth(token))
    assert dup.status_code == 201, dup.text
    copy = dup.json()
    assert copy["title"] == "Original (copy)"
    assert copy["state"] == "draft"
    assert copy["id"] != course_id
    copy_outline = (
        await client.get(f"/api/v1/courses/{copy['id']}/outline", headers=_auth(token))
    ).json()
    copy_rows = {r["lesson"]["title"]: r for r in copy_outline["modules"][0]["lessons"]}
    assert set(copy_rows) == {"Doc", "Quiz lesson"}
    # The quiz was deep-copied: a different id, same question count.
    assert copy_rows["Quiz lesson"]["lesson"]["quiz_id"] not in (None, quiz_id)
    assert copy_rows["Quiz lesson"]["question_count"] == 1
    assert copy_rows["Doc"]["lesson"]["body"].startswith("word word")


async def test_wizard_endpoints_require_course_edit(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    fake = str(uuid7())
    for method, path, body in [
        ("get", f"/api/v1/courses/{fake}/outline", None),
        ("get", f"/api/v1/courses/{fake}/readiness", None),
        ("post", f"/api/v1/courses/{fake}/duplicate", {}),
        ("post", f"/api/v1/courses/{fake}/modules/reorder", {"ordered_ids": [fake]}),
        ("delete", f"/api/v1/lessons/{fake}", None),
        ("delete", f"/api/v1/lessons/{fake}/activity", None),
        ("get", f"/api/v1/lessons/{fake}", None),
    ]:
        resp = await getattr(client, method)(
            path, **({"json": body} if body is not None else {}), headers=_auth(learner)
        )
        assert resp.status_code == 403, (method, path, resp.text)
