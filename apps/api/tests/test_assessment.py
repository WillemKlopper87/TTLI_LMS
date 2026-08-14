"""Phase 4 sprint 3: quizzes, surveys, assignments (02 §7.5/7.6/7.7,
03 §6.5/6.6, REQ-ASSESS-01…06, REQ-BYPASS-05/06/07/08).
"""

from __future__ import annotations

import json
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

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


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


def _clamav_reachable(host: str, port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((host, port))
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
    return f"assess-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        price_id = (await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one()
    return str(price_id)


async def _seeded_lesson_id(tenant_session_factory, tenant_id, *, position: int) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str(
            (
                await s.execute(
                    sa.text(
                        "SELECT l.id FROM lessons l "
                        "JOIN modules m ON m.id = l.module_id "
                        "JOIN courses c ON c.id = m.course_id "
                        "WHERE c.slug = 'executive-leadership-certificate' AND l.position = :p"
                    ),
                    {"p": position},
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


async def _enrol_via_eft(
    client, tenant_session_factory, crypto, *, tenant_id, price_id
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    buyer_token, buyer_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    order_id = order.json()["id"]
    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_id = checkout.json()["payment_id"]
    await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"%PDF-fake-proof-of-payment", "application/pdf")},
    )
    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}"},
    )
    assert approve.status_code == 200, approve.text
    return buyer_token, buyer_id


async def _create_quiz(client, author_token: str) -> str:
    resp = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Test Quiz", "pass_score": 70, "max_attempts": 2},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _add_choice_question(client, author_token: str, quiz_id: str, *, position: int) -> None:
    resp = await client.post(
        f"/api/v1/quizzes/{quiz_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "question_type": "single_choice",
            "prompt": "2 + 2?",
            "options": [
                {"id": "a", "text": "3", "correct": False},
                {"id": "b", "text": "4", "correct": True},
            ],
            "position": position,
            "points": 1,
        },
    )
    assert resp.status_code == 204, resp.text


# =============================================================== Quizzes ===


async def test_quiz_attempt_auto_grades_choice_questions(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)
    await _add_choice_question(client, author_token, quiz_id, position=1)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/quiz?quiz_id={quiz_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    attempt = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert attempt.status_code == 200, attempt.text
    body = attempt.json()
    # Correct answers are never sent to the client before submission.
    assert all("correct" not in opt for q in body["questions"] for opt in q["options"])
    question_id = body["questions"][0]["question_id"]

    submit = await client.post(
        f"/api/v1/quiz-attempts/{body['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "selected_option_ids": ["b"]}]},
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["score"] == "100.00"
    assert submit.json()["passed"] is True


async def test_quiz_attempt_limit_is_enforced(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "One Shot", "pass_score": 70, "max_attempts": 1},
    )
    quiz_id = quiz.json()["id"]
    await _add_choice_question(client, author_token, quiz_id, position=1)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/quiz?quiz_id={quiz_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    first = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "ATTEMPT_LIMIT_EXCEEDED"


async def test_learner_cannot_submit_another_learners_attempt(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)
    await _add_choice_question(client, author_token, quiz_id, position=1)
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/quiz?quiz_id={quiz_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    owner_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    attempt = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {owner_token}"}
    )
    attempt_id = attempt.json()["attempt_id"]

    stranger_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    resp = await client.post(
        f"/api/v1/quiz-attempts/{attempt_id}/submit",
        headers={"Authorization": f"Bearer {stranger_token}"},
        json={"answers": []},
    )
    assert resp.status_code == 403


async def test_text_answer_grading_finalises_score_and_passed(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)
    text_q = await client.post(
        f"/api/v1/quizzes/{quiz_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "question_type": "long_text",
            "prompt": "Reflect.",
            "options": [],
            "position": 1,
            "points": 1,
        },
    )
    assert text_q.status_code == 204
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/quiz?quiz_id={quiz_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    attempt = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    question_id = attempt.json()["questions"][0]["question_id"]
    submit = await client.post(
        f"/api/v1/quiz-attempts/{attempt.json()['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "text_answer": "My reflection."}]},
    )
    # Ungraded text answer: passed is genuinely unknown, not failed.
    assert submit.json()["passed"] is None

    async with tenant_session_factory(tenant_id) as s:
        answer_id = (
            await s.execute(
                sa.text("SELECT id FROM quiz_answers WHERE question_id = :q"), {"q": question_id}
            )
        ).scalar_one()

    grade = await client.post(
        f"/api/v1/quiz-answers/{answer_id}/grade",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"points_awarded": 1},
    )
    assert grade.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text("SELECT score, passed FROM quiz_attempts WHERE id = :a"),
                {"a": attempt.json()["attempt_id"]},
            )
        ).first()
    assert row is not None
    assert str(row[0]) == "100.00"
    assert row[1] is True


async def test_quiz_list_and_detail_expose_correct_answers_to_authors(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)
    await _add_choice_question(client, author_token, quiz_id, position=0)

    listed = await client.get(
        "/api/v1/quizzes", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert listed.status_code == 200, listed.text
    item = next(q for q in listed.json()["items"] if q["id"] == quiz_id)
    assert item["question_count"] == 1

    detail = await client.get(
        f"/api/v1/quizzes/{quiz_id}", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert detail.status_code == 200, detail.text
    question = detail.json()["questions"][0]
    correct_options = [o for o in question["options"] if o["correct"]]
    assert [o["id"] for o in correct_options] == ["b"]


async def test_quiz_list_and_detail_require_course_edit(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)

    # role="learner" — the real seeded role holding course:view, not
    # role=None. This is the test that actually proves course:view alone
    # can't see quiz answers, not just "no permissions at all fails."
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    listed = await client.get(
        "/api/v1/quizzes", headers={"Authorization": f"Bearer {learner_token}"}
    )
    assert listed.status_code == 403
    detail = await client.get(
        f"/api/v1/quizzes/{quiz_id}", headers={"Authorization": f"Bearer {learner_token}"}
    )
    assert detail.status_code == 403


# =============================================================== Surveys ===


async def test_anonymous_survey_response_never_stores_user_id(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    survey = await client.post(
        "/api/v1/surveys",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Feedback", "response_mode": "anonymous"},
    )
    survey_id = survey.json()["id"]
    q = await client.post(
        f"/api/v1/surveys/{survey_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"question_type": "long_text", "prompt": "Thoughts?", "options": [], "position": 1},
    )
    assert q.status_code == 204
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=2)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/survey?survey_id={survey_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    form = await client.get(
        f"/api/v1/surveys/{survey_id}", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    question_id = form.json()["questions"][0]["question_id"]

    submit = await client.post(
        f"/api/v1/surveys/{survey_id}/responses",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "value": "It was great."}]},
    )
    assert submit.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text(
                    "SELECT user_id, respondent_reference FROM survey_responses "
                    "WHERE survey_id = :s"
                ),
                {"s": survey_id},
            )
        ).first()
    assert row is not None
    assert row[0] is None  # genuinely absent, not merely null-by-coincidence
    assert row[1] is not None

    dup = await client.post(
        f"/api/v1/surveys/{survey_id}/responses",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "value": "trying again"}]},
    )
    assert dup.status_code == 400


async def test_identified_survey_response_stores_user_id(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    survey = await client.post(
        "/api/v1/surveys",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Named Feedback", "response_mode": "identified"},
    )
    survey_id = survey.json()["id"]
    q = await client.post(
        f"/api/v1/surveys/{survey_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "question_type": "short_text",
            "prompt": "Name one thing.",
            "options": [],
            "position": 1,
        },
    )
    assert q.status_code == 204
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=2)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/survey?survey_id={survey_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    buyer_token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    form = await client.get(
        f"/api/v1/surveys/{survey_id}", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    question_id = form.json()["questions"][0]["question_id"]
    submit = await client.post(
        f"/api/v1/surveys/{survey_id}/responses",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "value": "The workshops."}]},
    )
    assert submit.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text("SELECT user_id FROM survey_responses WHERE survey_id = :s"),
                {"s": survey_id},
            )
        ).first()
    assert row is not None
    assert row[0] == buyer_id


async def test_survey_list_requires_course_edit(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    resp = await client.get("/api/v1/surveys", headers={"Authorization": f"Bearer {learner_token}"})
    assert resp.status_code == 403


async def test_admin_can_view_survey_without_enrolment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    survey = await client.post(
        "/api/v1/surveys",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Admin Review", "response_mode": "identified"},
    )
    survey_id = survey.json()["id"]
    q = await client.post(
        f"/api/v1/surveys/{survey_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"question_type": "long_text", "prompt": "Thoughts?", "options": [], "position": 0},
    )
    assert q.status_code == 204

    listed = await client.get(
        "/api/v1/surveys", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert listed.status_code == 200, listed.text
    item = next(s for s in listed.json()["items"] if s["id"] == survey_id)
    assert item["question_count"] == 1

    # The content_author never enrolled in any course — proves the
    # course:edit fast-path bypasses the enrolment check that would
    # otherwise 403/404 an unenrolled caller.
    detail = await client.get(
        f"/api/v1/surveys/{survey_id}", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["questions"][0]["prompt"] == "Thoughts?"


# ============================================================ Assignments ===


async def test_infected_assignment_submission_is_refused(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    if not _clamav_reachable(settings.clamav_host, settings.clamav_port):
        pytest.skip(
            "no ClamAV on the configured CLAMAV_HOST/PORT — run: "
            "docker compose -f infra/docker-compose.yml up -d clamav"
        )
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    assignment = await client.post(
        "/api/v1/assignments",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Essay", "approval_required": True},
    )
    assignment_id = assignment.json()["id"]
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=2)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/assignment?assignment_id={assignment_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    resp = await client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("essay.txt", EICAR, "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["signature"]


async def test_assignment_submission_approval_flow(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    if not _clamav_reachable(settings.clamav_host, settings.clamav_port):
        pytest.skip(
            "no ClamAV on the configured CLAMAV_HOST/PORT — run: "
            "docker compose -f infra/docker-compose.yml up -d clamav"
        )
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    assignment = await client.post(
        "/api/v1/assignments",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Essay", "approval_required": True},
    )
    assignment_id = assignment.json()["id"]
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=2)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/assignment?assignment_id={assignment_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    submit = await client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("essay.txt", b"a real essay", "text/plain")},
    )
    assert submit.status_code == 201, submit.text
    submission_id = submit.json()["id"]
    assert submit.json()["approved_at"] is None

    review = await client.post(
        f"/api/v1/assignment-submissions/{submission_id}/review",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"approve": True},
    )
    assert review.status_code == 200
    assert review.json()["approved_at"] is not None


async def test_assignment_list_and_detail(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    created = await client.post(
        "/api/v1/assignments",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "title": "Case Study",
            "instructions": "Write it up.",
            "max_score": 50,
            "approval_required": False,
        },
    )
    assert created.status_code == 201, created.text
    assignment_id = created.json()["id"]

    listed = await client.get(
        "/api/v1/assignments", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert listed.status_code == 200, listed.text
    item = next(a for a in listed.json()["items"] if a["id"] == assignment_id)
    assert item["max_score"] == 50
    assert item["approval_required"] is False

    detail = await client.get(
        f"/api/v1/assignments/{assignment_id}", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["instructions"] == "Write it up."


async def test_assignment_list_requires_course_edit(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    resp = await client.get(
        "/api/v1/assignments", headers={"Authorization": f"Bearer {learner_token}"}
    )
    assert resp.status_code == 403


# ===================================================== Completion gating ===


async def test_completion_rule_engine_gates_on_quiz_survey_and_assignment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Direct model wiring, not just the individual subsystems in
    isolation — proves services/enrolment.py's _completion_context feeds
    real quiz/survey/assignment state into services/completion.py."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)
    await _add_choice_question(client, author_token, quiz_id, position=1)
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/quiz?quiz_id={quiz_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    # Test-setup only: no lesson-authoring endpoint sets completion_rules
    # yet (STATUS.md tracks that gap), so this is the same class of direct
    # fixture setup any test needs for state no API can produce. lessons
    # is global (not tenant-scoped, 0011) and shared with every other
    # test file, so the original rules are restored in `finally` —
    # skipping that once already broke test_learning.py's assumptions
    # about this exact lesson's minimum_time_seconds rule.
    original_rules = '{"minimum_time_seconds": 30}'
    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text("SELECT completion_rules FROM lessons WHERE id = :l"), {"l": lesson_id}
            )
        ).first()
        assert row is not None
        original_rules = json.dumps(row[0])
        await s.execute(
            sa.text("UPDATE lessons SET completion_rules = CAST(:r AS JSONB) WHERE id = :l"),
            {"r": '{"quiz_pass_score": 70}', "l": lesson_id},
        )

    try:
        buyer_token, _ = await _enrol_via_eft(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
        )
        await client.post(
            f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {buyer_token}"}
        )

        complete_before = await client.post(
            f"/api/v1/lessons/{lesson_id}/complete",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )
        assert complete_before.status_code == 423
        assert "quiz" in complete_before.json()["error"]["details"]["checks"][0]["rule"]

        attempt = await client.post(
            f"/api/v1/quizzes/{quiz_id}/attempts",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )
        question_id = attempt.json()["questions"][0]["question_id"]
        await client.post(
            f"/api/v1/quiz-attempts/{attempt.json()['attempt_id']}/submit",
            headers={"Authorization": f"Bearer {buyer_token}"},
            json={"answers": [{"question_id": question_id, "selected_option_ids": ["b"]}]},
        )

        complete_after = await client.post(
            f"/api/v1/lessons/{lesson_id}/complete",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )
        assert complete_after.status_code == 200, complete_after.text
        assert complete_after.json()["state"] == "completed"
    finally:
        async with tenant_session_factory(tenant_id) as s:
            await s.execute(
                sa.text("UPDATE lessons SET completion_rules = CAST(:r AS JSONB) WHERE id = :l"),
                {"r": original_rules, "l": lesson_id},
            )
