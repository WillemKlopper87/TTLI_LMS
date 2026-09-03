"""Phase 4 sprint 1: the completion rule engine, enrolments and lesson
progression (02 §5/§7, 03 §6, REQ-BYPASS-01/02/10/11). HTTP coverage for
the full path — buy the seeded course through the real EFT flow (same
helpers as test_commerce.py, duplicated per this project's existing
per-file convention), then start/complete lessons against the real API.
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
    return f"learner-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        price_id = (await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one()
    return str(price_id)


async def _seeded_lessons(tenant_session_factory, tenant_id) -> list[tuple[str, int]]:  # type: ignore[no-untyped-def]
    """The two document lessons 0011 seeds — [(lesson_id, position), ...]."""
    async with tenant_session_factory(tenant_id) as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT l.id, l.position FROM lessons l "
                    "JOIN modules m ON m.id = l.module_id "
                    "JOIN courses c ON c.id = m.course_id "
                    "WHERE c.slug = 'executive-leadership-certificate' "
                    "ORDER BY l.position"
                )
            )
        ).all()
    return [(str(row[0]), row[1]) for row in rows]


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
    """Drives a real order through the full EFT path to `fulfilled` — the
    only way an enrolment is created (services/orders.py::approve_eft), so
    this is the real path, not a shortcut around it."""
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

    await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"%PDF-fake-proof-of-payment", "application/pdf")},
    )
    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200, approve.text
    return buyer_token, buyer_id


async def _enrolment_id_for(tenant_session_factory, tenant_id, user_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str(
            (
                await s.execute(
                    sa.text("SELECT id FROM enrolments WHERE user_id = :u"), {"u": user_id}
                )
            ).scalar_one()
        )


async def _backdate_first_seen(
    tenant_session_factory, tenant_id, *, enrolment_id: str, lesson_id: str
) -> None:  # type: ignore[no-untyped-def]
    """Rather than sleeping past minimum_time_seconds (30s/60s — 0011's
    seed), push first_seen_at into the past. The rule engine only ever
    reads server-assigned timestamps (REQ-BYPASS-02); this changes the
    clock's input, not the app's evaluation logic. Scoped by enrolment_id
    too — lesson_id alone is shared by every learner enrolled in the
    seeded course, not unique on its own."""
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "UPDATE lesson_completions SET first_seen_at = now() - interval '1 hour' "
                "WHERE lesson_id = :l AND enrolment_id = :e"
            ),
            {"l": lesson_id, "e": enrolment_id},
        )


async def test_start_lesson_without_enrolment_is_forbidden(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, _ = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    resp = await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/start", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_complete_before_minimum_time_is_locked_with_reason(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )

    start = await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/start", headers={"Authorization": f"Bearer {token}"}
    )
    assert start.status_code == 204

    complete = await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/complete", headers={"Authorization": f"Bearer {token}"}
    )
    assert complete.status_code == 423
    body = complete.json()
    assert body["error"]["code"] == "LESSON_LOCKED"
    checks = body["error"]["details"]["checks"]
    assert any(c["rule"] == "minimum_time_seconds" and not c["met"] for c in checks)


async def test_last_lesson_cannot_be_started_before_prerequisites(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """C-2: prerequisite locking used to be computed for display only
    (`get_progress`'s `locked` flag) and never actually enforced — a
    learner could POST straight to the last lesson's /start, wait out
    its own minimum_time_seconds, /complete it, and walk away with a
    course certificate having never touched lesson 1. `start_lesson`
    must refuse this outright."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    last_lesson_id = lessons[-1][0]

    resp = await client.post(
        f"/api/v1/lessons/{last_lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 423, resp.text
    assert resp.json()["error"]["code"] == "LESSON_LOCKED"

    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text(
                    "SELECT 1 FROM lesson_completions lc "
                    "JOIN enrolments e ON e.id = lc.enrolment_id "
                    "WHERE e.user_id = :u AND lc.lesson_id = :l"
                ),
                {"u": buyer_id, "l": last_lesson_id},
            )
        ).first()
    assert row is None, "the refused start must not have created a completion row"


async def test_course_never_completes_with_incomplete_required_lessons(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """C-2's second half: `enrolment.completed_at` used to be set
    whenever `_next_lesson()` returned `None` — "this lesson is
    positionally last" — rather than "every lesson is actually
    complete". `start_lesson`'s own prerequisite check (regression-
    tested separately, above) closes the API path to this state, but
    `complete_lesson` must not rely on that invariant holding by
    construction alone — it re-checks independently. Simulated here by
    writing the pre-fix exploit's *precondition* straight into the
    database (an in-progress completion on the last lesson, with the
    first lesson never started), bypassing `start_lesson` on purpose to
    isolate this second, independent guard."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    last_lesson_id = lessons[-1][0]
    enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, buyer_id)

    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "INSERT INTO lesson_completions "
                "(id, tenant_id, enrolment_id, lesson_id, state, first_seen_at) "
                "VALUES (gen_random_uuid(), :t, :e, :l, 'in_progress', "
                "now() - interval '1 hour')"
            ),
            {"t": str(tenant_id), "e": enrolment_id, "l": last_lesson_id},
        )
        await s.commit()

    # The last lesson's own rule (minimum_time_seconds only) is satisfied
    # by the backdated first_seen_at, so completing *it* succeeds — what
    # must not happen is the course, or a certificate, completing off
    # the back of that alone while lesson 1 was never started.
    complete = await client.post(
        f"/api/v1/lessons/{last_lesson_id}/complete", headers={"Authorization": f"Bearer {token}"}
    )
    assert complete.status_code == 200, complete.text

    async with tenant_session_factory(tenant_id) as s:
        completed_at = (
            await s.execute(
                sa.text("SELECT completed_at FROM enrolments WHERE id = :e"), {"e": enrolment_id}
            )
        ).scalar_one()
        certificate_count = (
            await s.execute(
                sa.text("SELECT count(*) FROM certificates WHERE enrolment_id = :e"),
                {"e": enrolment_id},
            )
        ).scalar_one()
    assert completed_at is None, "the course must not complete while lesson 1 was never done"
    assert certificate_count == 0, "no certificate may be issued off the back of this"


async def test_start_is_idempotent(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )

    first = await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/start", headers={"Authorization": f"Bearer {token}"}
    )
    assert first.status_code == 204
    enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, buyer_id)
    async with tenant_session_factory(tenant_id) as s:
        first_seen = (
            await s.execute(
                sa.text(
                    "SELECT first_seen_at FROM lesson_completions "
                    "WHERE lesson_id = :l AND enrolment_id = :e"
                ),
                {"l": lessons[0][0], "e": enrolment_id},
            )
        ).scalar_one()

    second = await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/start", headers={"Authorization": f"Bearer {token}"}
    )
    assert second.status_code == 204
    async with tenant_session_factory(tenant_id) as s:
        still_first_seen = (
            await s.execute(
                sa.text(
                    "SELECT first_seen_at FROM lesson_completions "
                    "WHERE lesson_id = :l AND enrolment_id = :e"
                ),
                {"l": lessons[0][0], "e": enrolment_id},
            )
        ).scalar_one()
    assert still_first_seen == first_seen


async def test_complete_lesson_unlocks_next_and_updates_progress(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_1_id, lesson_2_id = lessons[0][0], lessons[1][0]

    async with tenant_session_factory(tenant_id) as s:
        enrolment_id = (
            await s.execute(
                sa.text("SELECT id FROM enrolments WHERE user_id = :u"), {"u": buyer_id}
            )
        ).scalar_one()

    # Before starting anything: lesson 1 available, lesson 2 locked.
    progress = await client.get(
        f"/api/v1/enrolments/{enrolment_id}/progress", headers={"Authorization": f"Bearer {token}"}
    )
    assert progress.status_code == 200
    rows = {row["lesson_id"]: row for row in progress.json()["lessons"]}
    assert rows[lesson_1_id]["state"] == "available"
    assert rows[lesson_2_id]["state"] == "locked"
    assert rows[lesson_2_id]["unmet_requirements"]

    await client.post(
        f"/api/v1/lessons/{lesson_1_id}/start", headers={"Authorization": f"Bearer {token}"}
    )
    await _backdate_first_seen(
        tenant_session_factory, tenant_id, enrolment_id=enrolment_id, lesson_id=lesson_1_id
    )

    complete = await client.post(
        f"/api/v1/lessons/{lesson_1_id}/complete", headers={"Authorization": f"Bearer {token}"}
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["state"] == "completed"
    assert complete.json()["next_lesson_id"] == lesson_2_id

    progress = await client.get(
        f"/api/v1/enrolments/{enrolment_id}/progress", headers={"Authorization": f"Bearer {token}"}
    )
    rows = {row["lesson_id"]: row for row in progress.json()["lessons"]}
    assert rows[lesson_1_id]["state"] == "completed"
    assert rows[lesson_2_id]["state"] == "available"


async def test_transcript_lists_only_completed_lessons_and_is_owner_only(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """REQ-LMS-06: the transcript is completed lessons only, each with the
    real completed_at the rule engine assigned — not the full progress
    checklist GET /enrolments/{id}/progress already serves."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_1_id = lessons[0][0]

    async with tenant_session_factory(tenant_id) as s:
        enrolment_id = (
            await s.execute(
                sa.text("SELECT id FROM enrolments WHERE user_id = :u"), {"u": buyer_id}
            )
        ).scalar_one()

    before = await client.get(
        f"/api/v1/enrolments/{enrolment_id}/transcript",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert before.status_code == 200, before.text
    assert before.json()["lessons"] == []
    assert before.json()["course_title"] == "Executive Leadership Certificate"
    assert "@" in before.json()["learner_name"]  # no full name captured — email fallback

    await client.post(
        f"/api/v1/lessons/{lesson_1_id}/start", headers={"Authorization": f"Bearer {token}"}
    )
    await _backdate_first_seen(
        tenant_session_factory, tenant_id, enrolment_id=enrolment_id, lesson_id=lesson_1_id
    )
    await client.post(
        f"/api/v1/lessons/{lesson_1_id}/complete", headers={"Authorization": f"Bearer {token}"}
    )

    after = await client.get(
        f"/api/v1/enrolments/{enrolment_id}/transcript",
        headers={"Authorization": f"Bearer {token}"},
    )
    rows = after.json()["lessons"]
    assert len(rows) == 1
    assert rows[0]["title"] == "Welcome"
    assert rows[0]["completed_at"] is not None

    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.get(
        f"/api/v1/enrolments/{enrolment_id}/transcript",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403


async def test_list_own_enrolments(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    token, _buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )

    resp = await client.get("/api/v1/enrolments", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["course_title"] == "Executive Leadership Certificate"
    assert rows[0]["started_at"] is None
    assert rows[0]["completed_at"] is None

    # A second learner's list must not include the first learner's row.
    other_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    other_resp = await client.get(
        "/api/v1/enrolments", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert other_resp.json() == []


async def test_progress_requires_ownership(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    _, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    other_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    async with tenant_session_factory(tenant_id) as s:
        enrolment_id = (
            await s.execute(
                sa.text("SELECT id FROM enrolments WHERE user_id = :u"), {"u": buyer_id}
            )
        ).scalar_one()

    resp = await client.get(
        f"/api/v1/enrolments/{enrolment_id}/progress",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403


async def test_completion_refusal_is_audit_logged(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    """REQ-BYPASS-11: every progression decision is audit-logged, including
    refusals."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )

    await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/start", headers={"Authorization": f"Bearer {token}"}
    )
    resp = await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/complete", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 423

    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text(
                    "SELECT actor_user_id, entity_id FROM audit_events "
                    "WHERE action = 'lesson.completion_refused' "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).first()
    assert row is not None
    assert str(row[0]) == str(buyer_id)
    assert str(row[1]) == lessons[0][0]


async def test_progress_carries_structured_checks_and_a_course_roll_up(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """`checks` is the full rule list — cleared rules included — beside
    the unchanged `unmet_requirements` refusal list, plus the course-level
    roll-up the learner shell's header renders."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    lesson_1_id = lessons[0][0]
    enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, buyer_id)

    before = await client.get(
        f"/api/v1/enrolments/{enrolment_id}/progress", headers={"Authorization": f"Bearer {token}"}
    )
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["progress_percent"] == 0
    assert body["next_lesson_id"] == lesson_1_id
    assert body["estimated_minutes"] >= 1
    assert body["estimated_minutes"] == sum(row["estimated_minutes"] for row in body["lessons"])

    first = next(row for row in body["lessons"] if row["lesson_id"] == lesson_1_id)
    assert first["module_title"] == "Getting Started"
    assert first["module_id"]
    assert isinstance(first["module_position"], int)
    # 0011 seeds lesson 1 with minimum_time_seconds: 30. Nothing has been
    # opened yet, so nought seconds of it are spent.
    check = next(c for c in first["checks"] if c["rule"] == "minimum_time_seconds")
    assert check["met"] is False
    assert check["current"] == "0:00"
    assert check["required"] == "0:30"

    await client.post(
        f"/api/v1/lessons/{lesson_1_id}/start", headers={"Authorization": f"Bearer {token}"}
    )
    await _backdate_first_seen(
        tenant_session_factory, tenant_id, enrolment_id=enrolment_id, lesson_id=lesson_1_id
    )
    complete = await client.post(
        f"/api/v1/lessons/{lesson_1_id}/complete", headers={"Authorization": f"Bearer {token}"}
    )
    assert complete.status_code == 200, complete.text

    after = (
        await client.get(
            f"/api/v1/enrolments/{enrolment_id}/progress",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    assert after["progress_percent"] == 50
    assert after["next_lesson_id"] == lessons[1][0]
    done = next(row for row in after["lessons"] if row["lesson_id"] == lesson_1_id)
    # A cleared rule is still reported — that is the whole point of
    # `checks` existing beside `unmet_requirements`, which stays empty.
    assert done["unmet_requirements"] == []
    met = next(c for c in done["checks"] if c["rule"] == "minimum_time_seconds")
    assert met["met"] is True
    assert met["required"] == "0:30"


async def test_dashboard_greets_the_learner_and_points_at_the_next_lesson(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, buyer_id)

    resp = await client.get("/api/v1/learn/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    board = resp.json()
    # No name was ever captured by the EFT purchase path.
    assert board["first_name"] is None
    assert len(board["initials"]) == 2
    assert board["stats"]["workshop_credits"] == 0
    assert board["stats"]["certificates"] == 0

    card = next(c for c in board["enrolments"] if c["enrolment_id"] == enrolment_id)
    assert card["course_title"] == "Executive Leadership Certificate"
    assert card["status"] == "not_started"
    assert card["progress_percent"] == 0
    assert card["lessons_total"] == 2
    assert card["lessons_completed"] == 0
    assert card["completed_at"] is None
    assert card["certificate"] is None
    assert card["next_lesson"]["title"] == "Welcome"
    assert card["next_lesson"]["module_title"] == "Getting Started"
    # Counted from the row order, not the stored position column — 0011
    # numbers its seed from 1 while the authoring service numbers from 0.
    assert card["next_lesson"]["position_label"] == "Module 1, lesson 1"

    await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/start", headers={"Authorization": f"Bearer {token}"}
    )
    await _backdate_first_seen(
        tenant_session_factory, tenant_id, enrolment_id=enrolment_id, lesson_id=lessons[0][0]
    )
    await client.post(
        f"/api/v1/lessons/{lessons[0][0]}/complete", headers={"Authorization": f"Bearer {token}"}
    )

    after = (
        await client.get("/api/v1/learn/dashboard", headers={"Authorization": f"Bearer {token}"})
    ).json()
    card = next(c for c in after["enrolments"] if c["enrolment_id"] == enrolment_id)
    assert card["status"] == "in_progress"
    assert card["progress_percent"] == 50
    assert card["lessons_completed"] == 1
    assert card["started_at"] is not None
    assert card["next_lesson"]["title"] == "Core Concepts"
    assert card["next_lesson"]["position_label"] == "Module 1, lesson 2"
    assert after["stats"]["in_progress"] == 1
    assert after["stats"]["completed"] == 0


async def test_dashboard_shows_only_the_callers_own_enrolments(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    board = (
        await client.get(
            "/api/v1/learn/dashboard", headers={"Authorization": f"Bearer {stranger_token}"}
        )
    ).json()
    assert board["enrolments"] == []
    assert board["upcoming"] == []
    assert board["stats"] == {
        "in_progress": 0,
        "completed": 0,
        "certificates": 0,
        "workshop_credits": 0,
    }


async def test_dashboard_is_unauthenticated_without_a_token(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/api/v1/learn/dashboard")).status_code == 401


async def test_dashboard_lists_an_open_quiz_as_an_upcoming_assessment(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """A quiz block the learner can sit right now is "upcoming" work,
    with the attempts the server would actually allow — the same count
    `services/quiz.py::start_attempt` enforces, not a client guess.

    The seeded course is global and shared with every other test file
    (0041: a lesson's content is now a sequence of blocks), so this test
    adds a new quiz block for the duration of the test and deletes it
    afterward, rather than mutating the lesson's existing block(s) —
    the same "don't permanently pollute shared seed data" discipline
    test_credentials.py uses for the course's template links.
    """
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lessons = await _seeded_lessons(tenant_session_factory, tenant_id)
    lesson_id = lessons[0][0]
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )

    quiz = await client.post(
        "/api/v1/quizzes",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Dashboard Readiness Check", "pass_score": 60, "max_attempts": 3},
    )
    assert quiz.status_code == 201, quiz.text
    quiz_id = quiz.json()["id"]

    block = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"block_type": "quiz"},
    )
    assert block.status_code == 201, block.text
    block_id = block.json()["id"]

    try:
        attach = await client.post(
            f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/quiz?quiz_id={quiz_id}",
            headers={"Authorization": f"Bearer {author_token}"},
        )
        assert attach.status_code == 204, attach.text

        token, buyer_id = await _enrol_via_eft(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
        )
        enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, buyer_id)

        board = (
            await client.get(
                "/api/v1/learn/dashboard", headers={"Authorization": f"Bearer {token}"}
            )
        ).json()
        item = next(
            u for u in board["upcoming"] if u["kind"] == "assessment" and u["quiz_id"] == quiz_id
        )
        assert item["title"] == "Dashboard Readiness Check"
        assert item["subtitle"] == "Executive Leadership Certificate"
        assert item["enrolment_id"] == enrolment_id
        assert item["lesson_id"] == lesson_id
        assert item["attempts_remaining"] == 3
        assert item["starts_at"] is None
        assert item["join_url"] is None
    finally:
        await client.delete(
            f"/api/v1/lessons/{lesson_id}/blocks/{block_id}",
            headers={"Authorization": f"Bearer {author_token}"},
        )
