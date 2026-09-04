"""Phase 4 sprint 3: quizzes, surveys, assignments (02 §7.5/7.6/7.7,
03 §6.5/6.6, REQ-ASSESS-01…06, REQ-BYPASS-05/06/07/08).
"""

from __future__ import annotations

import asyncio
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
from src.models.assessment import QuestionBankItem, SurveyQuestion, SurveyResponse
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


async def _tenant_id(tenant_session_factory, slug: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": slug})
        ).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        price_id = (await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one()
    return str(price_id)


@pytest.fixture(autouse=True)
async def _cleanup_seeded_lesson_blocks(tenant_session_factory):  # type: ignore[no-untyped-def]
    """The seeded course's lessons are global (0011) and shared with
    every other test file. Under the old one-activity-per-lesson model,
    re-attaching a quiz/survey/assignment just overwrote the lesson's
    one FK, so nothing accumulated. Under the block model (0041), every
    `_attach_quiz`/`_attach_survey`/`_attach_assignment` call in this
    file creates a brand new block — without cleanup, tests attaching to
    the same seeded lesson (position=1 or 2) would pile up blocks whose
    quizzes/surveys/assignments have no attempt for a *different* test's
    enrolment, which the completion aggregation (services/enrolment.py)
    correctly reads as "not all blocks satisfied" and locks the lesson.
    Deleting every non-text block after each test keeps the seeded
    lessons back at their original (migration-backfilled) shape."""
    yield
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "DELETE FROM lesson_blocks WHERE block_type != 'text' AND lesson_id IN ("
                "  SELECT l.id FROM lessons l "
                "  JOIN modules m ON m.id = l.module_id "
                "  JOIN courses c ON c.id = m.course_id "
                "  WHERE c.slug = 'executive-leadership-certificate'"
                ")"
            )
        )
        await s.commit()


async def _seeded_lesson_id(tenant_session_factory, tenant_id, *, position: int) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str(
            (
                await s.execute(
                    sa.text(
                        "SELECT l.id FROM lessons l "
                        "JOIN modules m ON m.id = l.module_id "
                        "JOIN courses c ON c.id = m.course_id "
                        "WHERE c.slug = 'executive-leadership-certificate' AND l.position = :p "
                        # The seeded lesson is the oldest row at that position: any
                        # test that appends a lesson to this shared course collides
                        # on `position` (create_lesson numbers from the row count,
                        # the seed from 1), and the shared test DB is never reset —
                        # `scalar_one()` on an unordered query then fails with
                        # MultipleResultsFound for every test using this helper.
                        "ORDER BY l.created_at LIMIT 1"
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
        headers={"Authorization": f"Bearer {buyer_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    order_id = order.json()["id"]
    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_id = checkout.json()["payment_id"]
    proof = await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"%PDF-fake-proof-of-payment", "application/pdf")},
    )
    assert proof.status_code == 204, proof.text
    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
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


async def _attach_quiz(client, author_token: str, lesson_id: str, quiz_id: str) -> str:
    """0041: attaching now targets a block, not the lesson directly —
    create the block, then attach. Returns the new block's id."""
    block = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"block_type": "quiz"},
    )
    assert block.status_code == 201, block.text
    block_id = block.json()["id"]
    attach = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/quiz?quiz_id={quiz_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert attach.status_code == 204, attach.text
    return block_id


async def _attach_survey(client, author_token: str, lesson_id: str, survey_id: str) -> str:
    block = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"block_type": "survey"},
    )
    assert block.status_code == 201, block.text
    block_id = block.json()["id"]
    attach = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/survey?survey_id={survey_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert attach.status_code == 204, attach.text
    return block_id


async def _attach_assignment(client, author_token: str, lesson_id: str, assignment_id: str) -> str:
    block = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"block_type": "assignment"},
    )
    assert block.status_code == 201, block.text
    block_id = block.json()["id"]
    attach = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/assignment?assignment_id={assignment_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert attach.status_code == 204, attach.text
    return block_id


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
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

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


async def test_quiz_submit_allows_grace_period_but_not_beyond_it(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Timed Quiz", "pass_score": 70, "max_attempts": 2, "time_limit_seconds": 30},
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["id"]
    await _add_choice_question(client, author_token, quiz_id, position=1)
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )

    async def _start_and_backdate(seconds_ago: int) -> str:
        attempt = await client.post(
            f"/api/v1/quizzes/{quiz_id}/attempts",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )
        assert attempt.status_code == 200, attempt.text
        attempt_id = attempt.json()["attempt_id"]
        async with tenant_session_factory(tenant_id) as s:
            await s.execute(
                sa.text(
                    "UPDATE quiz_attempts SET started_at = started_at - "
                    "make_interval(secs => :secs) WHERE id = :id"
                ),
                {"secs": seconds_ago, "id": attempt_id},
            )
            await s.commit()
        return attempt_id

    # 30s limit + 5s past it: inside the network-latency grace period, so
    # the client's own auto-submit-at-zero must still be accepted.
    within_grace_id = await _start_and_backdate(35)
    within_grace = await client.post(
        f"/api/v1/quiz-attempts/{within_grace_id}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": []},
    )
    assert within_grace.status_code == 200, within_grace.text

    # 30s limit + 20s past it: beyond the grace period -- genuinely late,
    # not just a slow network round-trip, so this must still be refused.
    beyond_grace_id = await _start_and_backdate(50)
    beyond_grace = await client.post(
        f"/api/v1/quiz-attempts/{beyond_grace_id}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": []},
    )
    assert beyond_grace.status_code == 400, beyond_grace.text
    assert beyond_grace.json()["error"]["code"] == "TIME_LIMIT_EXCEEDED"


async def test_quiz_attempt_limit_is_enforced(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    """Starting again while the one allowed attempt is still *open*
    resumes it (H-8) rather than refusing — that guarantee has its own
    dedicated test below. The limit itself only bites once that attempt
    is actually spent (submitted), which is what this test drives to."""
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
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    first = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert first.status_code == 200
    question_id = first.json()["questions"][0]["question_id"]
    submitted = await client.post(
        f"/api/v1/quiz-attempts/{first.json()['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "selected_option_ids": ["b"]}]},
    )
    assert submitted.status_code == 200, submitted.text

    second = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "ATTEMPT_LIMIT_EXCEEDED"


async def test_parallel_quiz_starts_with_none_open_resume_into_one_attempt(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """H-7 + H-8 together: two parallel *first-ever* starts used to both
    count 0 existing attempts and both insert `attempt_number=1`,
    exceeding `max_attempts=1`. The enrolment row is now locked for the
    duration of the count-then-insert (mirrors `test_workshops.py::
    test_concurrent_bookings_cannot_oversell_the_last_seat`'s pattern for
    the same class of race) — and because H-8 also makes a second call
    resume an already-open attempt rather than refuse outright, the
    loser of that lock race doesn't see ATTEMPT_LIMIT_EXCEEDED any more;
    it transparently resumes the winner's attempt instead. Either way,
    never more than one attempt actually exists."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "One Shot Race", "pass_score": 70, "max_attempts": 1},
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["id"]
    await _add_choice_question(client, author_token, quiz_id, position=1)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    async def _start():  # type: ignore[no-untyped-def]
        return await client.post(
            f"/api/v1/quizzes/{quiz_id}/attempts",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )

    first, second = await asyncio.gather(_start(), _start())
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["attempt_id"] == second.json()["attempt_id"]

    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM quiz_attempts WHERE quiz_id = :q"), {"q": quiz_id}
            )
        ).scalar_one()
    assert count == 1, "exactly one attempt must exist, never two, even under a race"


async def test_parallel_quiz_starts_cannot_exceed_an_already_exhausted_limit(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """H-7's original race, once the one allowed attempt is actually
    spent (submitted, so H-8 has nothing open left to resume): two
    parallel starts used to both count 1 existing attempt and both pass
    the `>= max_attempts` check before either committed, exceeding
    `max_attempts=1`. The enrolment-row lock now serialises them."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "One Shot Race Exhausted", "pass_score": 70, "max_attempts": 1},
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["id"]
    await _add_choice_question(client, author_token, quiz_id, position=1)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    spent = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert spent.status_code == 200, spent.text
    question_id = spent.json()["questions"][0]["question_id"]
    submitted = await client.post(
        f"/api/v1/quiz-attempts/{spent.json()['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "selected_option_ids": ["b"]}]},
    )
    assert submitted.status_code == 200, submitted.text

    async def _start():  # type: ignore[no-untyped-def]
        return await client.post(
            f"/api/v1/quizzes/{quiz_id}/attempts",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )

    first, second = await asyncio.gather(_start(), _start())
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [400, 400], (first.text, second.text)
    assert first.json()["error"]["code"] == "ATTEMPT_LIMIT_EXCEEDED"
    assert second.json()["error"]["code"] == "ATTEMPT_LIMIT_EXCEEDED"

    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM quiz_attempts WHERE quiz_id = :q"), {"q": quiz_id}
            )
        ).scalar_one()
    assert count == 1, "the exhausted limit must never grow, even under a race"


async def test_starting_a_quiz_with_an_open_attempt_resumes_it(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """H-8: the quiz player POSTs `/quizzes/{id}/attempts` on every mount
    (a reload, navigating away and back, React StrictMode's double-
    invoke) — with no resume path, each of those consumed a real attempt
    against `max_attempts` before the learner had answered anything, so
    a `max_attempts: 1` quiz could read as "no attempts remaining" from
    a single reload. Starting again while an attempt is still open
    (never submitted) must return that same attempt, not a new one."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Resumable", "pass_score": 70, "max_attempts": 1},
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["id"]
    await _add_choice_question(client, author_token, quiz_id, position=1)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    first = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert first.status_code == 200, first.text
    first_body = first.json()

    # Simulates the component remounting (reload, tab switch, StrictMode)
    # before the learner has answered or submitted anything.
    second = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert second.status_code == 200, second.text
    second_body = second.json()

    assert second_body["attempt_id"] == first_body["attempt_id"]
    assert second_body["attempt_number"] == first_body["attempt_number"] == 1
    assert second_body["attempts_remaining"] == first_body["attempts_remaining"] == 0

    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM quiz_attempts WHERE quiz_id = :q"), {"q": quiz_id}
            )
        ).scalar_one()
    assert count == 1, "resuming must not have created a second attempt row"

    # The attempt is still genuinely usable — max_attempts=1 must not
    # itself have been silently exhausted by the remount.
    question_id = second_body["questions"][0]["question_id"]
    submit = await client.post(
        f"/api/v1/quiz-attempts/{second_body['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "selected_option_ids": ["b"]}]},
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["passed"] is True


async def test_starting_a_quiz_after_the_open_attempt_expired_issues_a_fresh_one(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """H-8's edge case: an open attempt that genuinely timed out without
    ever being submitted must not trap the learner on a dead row forever
    — it is not resumable, and a fresh attempt (still counted against
    max_attempts, exactly as before this fix) is issued instead."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "title": "Resumable Timed",
            "pass_score": 70,
            "max_attempts": 2,
            "time_limit_seconds": 30,
        },
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["id"]
    await _add_choice_question(client, author_token, quiz_id, position=1)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    first = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert first.status_code == 200, first.text
    first_attempt_id = first.json()["attempt_id"]

    # Push it well past its 30s limit + grace period without ever
    # submitting, the same backdating trick used elsewhere in this file.
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "UPDATE quiz_attempts SET started_at = started_at - interval '90 seconds' "
                "WHERE id = :id"
            ),
            {"id": first_attempt_id},
        )
        await s.commit()

    second = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["attempt_id"] != first_attempt_id
    assert second.json()["attempt_number"] == 2


async def test_parallel_submits_of_the_same_attempt_do_not_double_count_answers(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """H-7's other race: `submit_attempt`'s `submitted_at is not None`
    check used to be check-then-act with no lock — two concurrent
    submits of the *same* attempt could both pass it and both insert a
    full set of `QuizAnswer` rows, double-counting points in
    `grade_text_answer`'s re-finalised score. The attempt row is now
    locked for the duration of the check and the answer writes, and
    `uq_quiz_answers_attempt_question` (0044) backstops it at the
    database layer."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)
    await _add_choice_question(client, author_token, quiz_id, position=1)
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    attempt = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert attempt.status_code == 200, attempt.text
    attempt_id = attempt.json()["attempt_id"]
    question_id = attempt.json()["questions"][0]["question_id"]
    payload = {"answers": [{"question_id": question_id, "selected_option_ids": ["b"]}]}

    async def _submit():  # type: ignore[no-untyped-def]
        return await client.post(
            f"/api/v1/quiz-attempts/{attempt_id}/submit",
            headers={"Authorization": f"Bearer {buyer_token}"},
            json=payload,
        )

    first, second = await asyncio.gather(_submit(), _submit())
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 400], (first.text, second.text)

    async with tenant_session_factory(tenant_id) as s:
        answer_count = (
            await s.execute(
                sa.text("SELECT count(*) FROM quiz_answers WHERE attempt_id = :a"),
                {"a": attempt_id},
            )
        ).scalar_one()
    assert answer_count == 1, "one answer per question, never doubled by a racing submit"


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
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

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
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

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


async def test_list_ungraded_quiz_answers_then_grading_removes_it(
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
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    buyer_me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    buyer_email = buyer_me.json()["email"]
    attempt = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    question_id = attempt.json()["questions"][0]["question_id"]
    await client.post(
        f"/api/v1/quiz-attempts/{attempt.json()['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "text_answer": "My reflection."}]},
    )

    queue = await client.get(
        "/api/v1/quiz-answers/ungraded", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert queue.status_code == 200, queue.text
    row = next(r for r in queue.json()["items"] if r["quiz_id"] == quiz_id)
    assert row["prompt"] == "Reflect."
    assert row["text_answer"] == "My reflection."
    assert row["points_possible"] == 1
    assert row["learner_email"] == buyer_email

    grade = await client.post(
        f"/api/v1/quiz-answers/{row['answer_id']}/grade",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"points_awarded": 1},
    )
    assert grade.status_code == 204

    queue_after = await client.get(
        "/api/v1/quiz-answers/ungraded", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert all(r["quiz_id"] != quiz_id for r in queue_after.json()["items"])


async def test_list_ungraded_quiz_answers_requires_quiz_grade_permission(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    # role="learner" — the real seeded role, not role=None, to actually
    # prove a learner can't browse other learners' ungraded answers.
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    resp = await client.get(
        "/api/v1/quiz-answers/ungraded", headers={"Authorization": f"Bearer {learner_token}"}
    )
    assert resp.status_code == 403


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
    await _attach_survey(client, author_token, lesson_id, survey_id)

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
    await _attach_survey(client, author_token, lesson_id, survey_id)

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


async def test_question_bank_is_tenant_scoped_permission_gated_and_reusable(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    headers = {"Authorization": f"Bearer {author_token}"}
    created = await client.post(
        "/api/v1/question-bank",
        headers=headers,
        json={
            "assessment_kind": "quiz",
            "question_type": "single_choice",
            "prompt": "Which principle comes first?",
            "options": [
                {"id": "people", "text": "People", "correct": True},
                {"id": "process", "text": "Process", "correct": False},
            ],
            "points": 2,
        },
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    listed = await client.get("/api/v1/question-bank?assessment_kind=quiz", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [item_id]

    acme_id = await _tenant_id(tenant_session_factory, "acme")
    async with tenant_session_factory(acme_id) as session:
        assert (await session.execute(sa.select(QuestionBankItem))).scalars().all() == []

    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    forbidden = await client.get(
        "/api/v1/question-bank", headers={"Authorization": f"Bearer {learner_token}"}
    )
    assert forbidden.status_code == 403

    quiz = await client.post(
        "/api/v1/quizzes",
        headers=headers,
        json={"title": "Bank target", "pass_score": 70, "max_attempts": 1},
    )
    quiz_id = quiz.json()["id"]
    applied = await client.post(
        f"/api/v1/quizzes/{quiz_id}/questions/from-bank/{item_id}",
        headers=headers,
        json={"position": 0},
    )
    assert applied.status_code == 204, applied.text
    detail = await client.get(f"/api/v1/quizzes/{quiz_id}", headers=headers)
    question = detail.json()["questions"][0]
    assert question["prompt"] == "Which principle comes first?"
    assert question["points"] == 2
    assert question["options"][0]["correct"] is True

    survey_item = await client.post(
        "/api/v1/question-bank",
        headers=headers,
        json={
            "assessment_kind": "survey",
            "question_type": "long_text",
            "prompt": "What will you apply?",
            "options": [],
        },
    )
    survey = await client.post(
        "/api/v1/surveys",
        headers=headers,
        json={"title": "Bank survey", "response_mode": "identified"},
    )
    survey_id = survey.json()["id"]
    survey_applied = await client.post(
        f"/api/v1/surveys/{survey_id}/questions/from-bank/{survey_item.json()['id']}",
        headers=headers,
        json={"position": 0},
    )
    assert survey_applied.status_code == 204, survey_applied.text
    survey_detail = await client.get(f"/api/v1/surveys/{survey_id}", headers=headers)
    assert survey_detail.json()["questions"][0]["prompt"] == "What will you apply?"

    deleted = await client.delete(f"/api/v1/question-bank/{item_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    detail_after_delete = await client.get(f"/api/v1/quizzes/{quiz_id}", headers=headers)
    assert detail_after_delete.json()["questions"][0]["prompt"] == question["prompt"]


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


async def test_survey_results_requires_course_edit(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    survey = await client.post(
        "/api/v1/surveys",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Gate Check", "response_mode": "anonymous"},
    )
    survey_id = survey.json()["id"]

    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    resp = await client.get(
        f"/api/v1/surveys/{survey_id}/results",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403


async def test_survey_results_gated_until_minimum_group_size(
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
        json={"title": "Session Rating", "response_mode": "anonymous", "minimum_group_size": 2},
    )
    survey_id = survey.json()["id"]
    q = await client.post(
        f"/api/v1/surveys/{survey_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "question_type": "single_choice",
            "prompt": "How was the session?",
            "options": [{"id": "good", "text": "Good"}, {"id": "bad", "text": "Bad"}],
            "position": 0,
        },
    )
    assert q.status_code == 204
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=2)
    await _attach_survey(client, author_token, lesson_id, survey_id)

    async def _respond(value: str) -> None:
        buyer_token, _ = await _enrol_via_eft(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
        )
        form = await client.get(
            f"/api/v1/surveys/{survey_id}",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )
        question_id = form.json()["questions"][0]["question_id"]
        submit = await client.post(
            f"/api/v1/surveys/{survey_id}/responses",
            headers={"Authorization": f"Bearer {buyer_token}"},
            json={"answers": [{"question_id": question_id, "value": value}]},
        )
        assert submit.status_code == 204

    await _respond("good")

    below = await client.get(
        f"/api/v1/surveys/{survey_id}/results",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert below.status_code == 200, below.text
    body = below.json()
    assert body["response_count"] == 1
    assert body["available"] is False
    assert body["questions"] == []

    await _respond("bad")

    reached = await client.get(
        f"/api/v1/surveys/{survey_id}/results",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert reached.status_code == 200, reached.text
    body = reached.json()
    assert body["response_count"] == 2
    assert body["available"] is True
    assert len(body["questions"]) == 1
    counts = body["questions"][0]["counts"]
    assert counts == {"good": 1, "bad": 1}
    assert body["questions"][0]["response_count"] == 2

    csv_resp = await client.get(
        f"/api/v1/surveys/{survey_id}/results/export.csv",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert "text/csv" in csv_resp.headers["content-type"]
    csv_text = csv_resp.text
    assert "How was the session?" in csv_text
    assert "Good" in csv_text and "Bad" in csv_text


async def test_survey_results_never_exposes_free_text_answers(
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
        json={"title": "Open Feedback", "response_mode": "anonymous", "minimum_group_size": 1},
    )
    survey_id = survey.json()["id"]
    q = await client.post(
        f"/api/v1/surveys/{survey_id}/questions",
        headers={"Authorization": f"Bearer {author_token}"},
        json={
            "question_type": "long_text",
            "prompt": "Anything else?",
            "options": [],
            "position": 0,
        },
    )
    assert q.status_code == 204
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=2)
    await _attach_survey(client, author_token, lesson_id, survey_id)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    form = await client.get(
        f"/api/v1/surveys/{survey_id}",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    question_id = form.json()["questions"][0]["question_id"]
    secret_text = "The facilitator's shoes were a distraction, honestly."
    submit = await client.post(
        f"/api/v1/surveys/{survey_id}/responses",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "value": secret_text}]},
    )
    assert submit.status_code == 204

    results = await client.get(
        f"/api/v1/surveys/{survey_id}/results",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert results.status_code == 200, results.text
    assert secret_text not in results.text
    body = results.json()
    assert body["available"] is True
    assert len(body["questions"]) == 1
    assert body["questions"][0]["counts"] is None
    assert body["questions"][0]["response_count"] == 1

    csv_resp = await client.get(
        f"/api/v1/surveys/{survey_id}/results/export.csv",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert secret_text not in csv_resp.text


async def test_pre_post_delta_requires_both_privacy_thresholds(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    headers = {"Authorization": f"Bearer {author_token}"}
    pre = await client.post(
        "/api/v1/surveys",
        headers=headers,
        json={
            "title": "Confidence before",
            "response_mode": "anonymous",
            "minimum_group_size": 2,
            "evaluation_role": "pre",
        },
    )
    assert pre.status_code == 201, pre.text
    pre_body = pre.json()
    assert pre_body["pair_id"]
    post = await client.post(
        "/api/v1/surveys",
        headers=headers,
        json={
            "title": "Confidence after",
            "response_mode": "anonymous",
            "minimum_group_size": 2,
            "evaluation_role": "post",
            "paired_survey_id": pre_body["id"],
        },
    )
    assert post.status_code == 201, post.text
    assert post.json()["pair_id"] == pre_body["pair_id"]

    question_ids: dict[str, uuid.UUID] = {}
    for stage, survey_id, option_prefix in (
        ("pre", pre_body["id"], "before"),
        ("post", post.json()["id"], "after"),
    ):
        question_id = uuid.uuid4()
        question_ids[stage] = question_id
        async with tenant_session_factory(tenant_id) as session:
            session.add(
                SurveyQuestion(
                    id=question_id,
                    survey_id=uuid.UUID(survey_id),
                    question_type="single_choice",
                    prompt="How confident are you?",
                    options=[
                        {"id": f"{option_prefix}-low", "text": "Low"},
                        {"id": f"{option_prefix}-high", "text": "High"},
                    ],
                    position=0,
                )
            )
            await session.commit()

    async def add_response(stage: str, value: str) -> None:
        survey_id = pre_body["id"] if stage == "pre" else post.json()["id"]
        async with tenant_session_factory(tenant_id) as session:
            session.add(
                SurveyResponse(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    survey_id=uuid.UUID(survey_id),
                    user_id=None,
                    respondent_reference=uuid.uuid4().bytes,
                    answers=[{"question_id": str(question_ids[stage]), "value": value}],
                )
            )
            await session.commit()

    await add_response("pre", "before-low")
    await add_response("pre", "before-high")
    await add_response("post", "after-high")
    below = await client.get(f"/api/v1/surveys/{pre_body['id']}/delta", headers=headers)
    assert below.status_code == 200, below.text
    assert below.json()["available"] is False
    assert below.json()["questions"] == []

    await add_response("post", "after-high")
    reached = await client.get(f"/api/v1/surveys/{pre_body['id']}/delta", headers=headers)
    assert reached.status_code == 200, reached.text
    body = reached.json()
    assert body["available"] is True
    low, high = body["questions"][0]["options"]
    assert low["delta_percentage_points"] == -50.0
    assert high["delta_percentage_points"] == 50.0

    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    forbidden = await client.get(
        f"/api/v1/surveys/{pre_body['id']}/delta",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert forbidden.status_code == 403


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
    await _attach_assignment(client, author_token, lesson_id, assignment_id)

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
    await _attach_assignment(client, author_token, lesson_id, assignment_id)

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


async def test_parallel_assignment_submissions_never_share_a_version(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    """H-7's assignment-side race: `assignment.py::submit` used to read
    the latest submission's version then insert `version + 1` with no
    lock — two parallel submissions for the same (enrolment, assignment)
    could both read the same latest version and both insert the same
    next one. The enrolment row is now locked for the duration of the
    read-then-insert, and `uq_assignment_submissions_enrolment_
    assignment_version` (0044) backstops it at the database layer."""
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
        json={"title": "Racing Essay", "approval_required": False},
    )
    assert assignment.status_code == 201, assignment.text
    assignment_id = assignment.json()["id"]
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=2)
    await _attach_assignment(client, author_token, lesson_id, assignment_id)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )

    async def _submit():  # type: ignore[no-untyped-def]
        return await client.post(
            f"/api/v1/assignments/{assignment_id}/submissions",
            headers={"Authorization": f"Bearer {buyer_token}"},
            files={"file": ("essay.txt", b"a real essay", "text/plain")},
        )

    first, second = await asyncio.gather(_submit(), _submit())
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    versions = sorted([first.json()["version"], second.json()["version"]])
    assert versions == [1, 2], "both submissions must land, with two distinct versions"

    async with tenant_session_factory(tenant_id) as s:
        distinct_versions = (
            await s.execute(
                sa.text(
                    "SELECT count(DISTINCT version) FROM assignment_submissions "
                    "WHERE assignment_id = :a"
                ),
                {"a": assignment_id},
            )
        ).scalar_one()
    assert distinct_versions == 2, "no two submissions may share a version, even under a race"


async def test_list_pending_assignment_submissions_then_review_removes_it(
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
    await _attach_assignment(client, author_token, lesson_id, assignment_id)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    buyer_me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    buyer_email = buyer_me.json()["email"]
    submit = await client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("essay.txt", b"a real essay", "text/plain")},
    )
    assert submit.status_code == 201, submit.text
    submission_id = submit.json()["id"]

    pending = await client.get(
        "/api/v1/assignment-submissions/pending",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert pending.status_code == 200, pending.text
    row = next(r for r in pending.json()["items"] if r["submission_id"] == submission_id)
    assert row["assignment_id"] == assignment_id
    assert row["assignment_title"] == "Essay"
    assert row["learner_email"] == buyer_email
    assert row["version"] == 1

    download = await client.get(
        f"/api/v1/assignment-submissions/{submission_id}/download",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert download.status_code == 200, download.text
    # The file itself, not a storage URL for the browser to chase: the
    # local backend's "signed URL" is file://, which no page on http://
    # can open, and Garage isn't reachable from a browser on the single-VM
    # deployment either — so this endpoint streams the bytes.
    assert download.content == b"a real essay"
    assert download.headers["content-type"].startswith("text/plain")
    assert 'attachment; filename="essay.txt"' in download.headers["content-disposition"]

    review = await client.post(
        f"/api/v1/assignment-submissions/{submission_id}/review",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"approve": True},
    )
    assert review.status_code == 200

    pending_after = await client.get(
        "/api/v1/assignment-submissions/pending",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert all(r["submission_id"] != submission_id for r in pending_after.json()["items"])


async def test_pending_assignment_submissions_require_quiz_grade_permission(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    # role="learner" — the real seeded role, not role=None, to actually
    # prove a learner can't browse other learners' submissions.
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    resp = await client.get(
        "/api/v1/assignment-submissions/pending",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403
    download = await client.get(
        f"/api/v1/assignment-submissions/{uuid.uuid4()}/download",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert download.status_code == 403


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
    await _attach_quiz(client, author_token, lesson_id, quiz_id)
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


async def test_quiz_attempt_payload_states_the_rules_of_the_sitting(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The learner should not have to guess the pass mark or how many
    goes they have left. `attempts_remaining` counts what is left *after*
    the attempt just started, using the same arithmetic
    `services/quiz.py::start_attempt` enforces the limit with."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    quiz_id = await _create_quiz(client, author_token)  # pass_score 70, max_attempts 2
    await _add_choice_question(client, author_token, quiz_id, position=1)

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await _attach_quiz(client, author_token, lesson_id, quiz_id)

    first = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["quiz_title"] == "Test Quiz"
    assert body["pass_score"] == 70
    assert body["max_attempts"] == 2
    assert body["attempt_number"] == 1
    assert body["attempts_remaining"] == 1
    assert body["randomise_questions"] is False
    assert body["randomise_options"] is False
    # Every field the endpoint already returned is still there.
    assert body["attempt_id"]
    assert body["quiz_id"] == quiz_id
    assert body["time_limit_seconds"] is None
    assert len(body["questions"]) == 1

    # Submitted (H-8: a still-open attempt would just be *resumed* by the
    # next /attempts call, not superseded by a genuinely new one) — this
    # is the real path to a second attempt existing at all.
    question_id = body["questions"][0]["question_id"]
    submitted = await client.post(
        f"/api/v1/quiz-attempts/{body['attempt_id']}/submit",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={"answers": [{"question_id": question_id, "selected_option_ids": ["a"]}]},
    )
    assert submitted.status_code == 200, submitted.text

    second = await client.post(
        f"/api/v1/quizzes/{quiz_id}/attempts", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["attempt_number"] == 2
    assert second.json()["attempts_remaining"] == 0
