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
    token, buyer_id = await _enrol_via_eft(
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
