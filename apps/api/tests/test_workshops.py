"""Phase 5 sprint 3: workshops, facilitators, booking (02 §9, REQ-WS-01
through REQ-WS-09). HTTP coverage for one complete booking path — a
facilitator with real availability, a session, capacity enforcement
with a real waitlist, facilitator-overridable attendance, and the
manual meeting-provider fallback.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.models.commerce import Entitlement
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
    return f"ws-{uuid.uuid4().hex[:12]}@example.com"


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


def _next_weekday_at(day_of_week: int, hour: int) -> datetime:
    """The next date matching `day_of_week` (0=Monday), at `hour:00` UTC,
    far enough out that "now" can never collide with the window."""
    now = datetime.now(UTC) + timedelta(days=14)
    delta = (day_of_week - now.weekday()) % 7
    target = now + timedelta(days=delta)
    return target.replace(hour=hour, minute=0, second=0, microsecond=0)


async def _make_facilitator(
    client, admin_token: str, tenant_session_factory, crypto, *, tenant_id
) -> tuple[str, str, str]:  # type: ignore[no-untyped-def]
    """(facilitator_id, facilitator_token, facilitator_email) — a real
    facilitator-role user, registered as a facilitator, with a Tuesday
    09:00-12:00 UTC availability window."""
    facilitator_token, _, facilitator_email = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="facilitator"
    )
    created = await client.post(
        "/api/v1/facilitators",
        json={"email": facilitator_email, "bio": "Leadership coach"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    facilitator_id = created.json()["id"]

    availability = await client.post(
        f"/api/v1/facilitators/{facilitator_id}/availability",
        json={"day_of_week": 1, "start_time": "09:00", "end_time": "12:00"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert availability.status_code == 201, availability.text
    return facilitator_id, facilitator_token, facilitator_email


async def _make_workshop(client, admin_token: str) -> str:
    resp = await client.post(
        "/api/v1/workshops",
        json={
            "title": "Executive Coaching Debrief",
            "session_type": "one_on_one",
            "default_duration_minutes": 60,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_only_workshop_manage_can_create_facilitators_and_workshops(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.post(
        "/api/v1/workshops",
        json={"title": "X", "session_type": "one_on_one"},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert forbidden.status_code == 403


async def test_session_rejected_outside_facilitator_availability(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    # Wednesday, not the Tuesday window the facilitator is available.
    starts = _next_weekday_at(2, 10)
    resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text
    assert "availability" in resp.json()["error"]["message"].lower()


async def test_session_rejected_on_facilitator_double_booking(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    starts = _next_weekday_at(1, 9)
    first = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert first.status_code == 201, first.text

    overlapping = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": (starts + timedelta(minutes=30)).isoformat(),
            "ends_at": (starts + timedelta(hours=1, minutes=30)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert overlapping.status_code == 400, overlapping.text
    assert "already has a session" in overlapping.json()["error"]["message"].lower()


async def test_booking_fills_capacity_then_waitlists_and_cancel_promotes(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, facilitator_token, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    starts = _next_weekday_at(1, 9)
    session_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 1,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert session_resp.status_code == 201, session_resp.text
    session_id = session_resp.json()["id"]

    learner_a_token, _, learner_a_email = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    learner_b_token, _, learner_b_email = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    booking_a = await client.post(
        f"/api/v1/sessions/{session_id}/book",
        headers={"Authorization": f"Bearer {learner_a_token}"},
    )
    assert booking_a.status_code == 200, booking_a.text
    assert booking_a.json()["status"] == "registered"
    # The manual provider always succeeds but never fabricates a join
    # URL — the facilitator supplies one by hand (REQ-WS-06).
    assert booking_a.json()["join_url"] is None

    booking_b = await client.post(
        f"/api/v1/sessions/{session_id}/book",
        headers={"Authorization": f"Bearer {learner_b_token}"},
    )
    assert booking_b.status_code == 200, booking_b.text
    assert booking_b.json()["status"] == "waitlisted"
    booking_b_id = booking_b.json()["id"]

    # A second attempt by the same learner is refused, not a duplicate.
    duplicate = await client.post(
        f"/api/v1/sessions/{session_id}/book",
        headers={"Authorization": f"Bearer {learner_a_token}"},
    )
    assert duplicate.status_code == 400

    booking_a_id = booking_a.json()["id"]
    cancelled = await client.post(
        f"/api/v1/bookings/{booking_a_id}/cancel",
        headers={"Authorization": f"Bearer {learner_a_token}"},
    )
    assert cancelled.status_code == 204, cancelled.text

    roster = await client.get(
        f"/api/v1/sessions/{session_id}/roster",
        headers={"Authorization": f"Bearer {facilitator_token}"},
    )
    assert roster.status_code == 200, roster.text
    rows = {r["email"]: r for r in roster.json()["items"]}
    assert rows[learner_a_email]["booking_status"] == "cancelled"
    # Learner B was promoted off the waitlist once A's seat freed up.
    assert rows[learner_b_email]["booking_status"] == "registered"
    assert rows[learner_b_email]["booking_id"] == booking_b_id


async def test_facilitator_can_override_attendance_and_roster_is_gated(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, facilitator_token, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    starts = _next_weekday_at(1, 9)
    session_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 3,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    session_id = session_resp.json()["id"]

    learner_token, learner_id, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    await client.post(
        f"/api/v1/sessions/{session_id}/book", headers={"Authorization": f"Bearer {learner_token}"}
    )

    # A stranger — neither this session's facilitator nor workshop:manage — is refused.
    stranger_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.get(
        f"/api/v1/sessions/{session_id}/roster",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403

    marked = await client.post(
        f"/api/v1/sessions/{session_id}/attendance",
        json={"user_id": str(learner_id), "status": "attended"},
        headers={"Authorization": f"Bearer {facilitator_token}"},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["attendance_status"] == "attended"

    roster = await client.get(
        f"/api/v1/sessions/{session_id}/roster",
        headers={"Authorization": f"Bearer {facilitator_token}"},
    )
    assert roster.json()["items"][0]["attendance_status"] == "attended"


async def test_public_workshops_lists_upcoming_sessions_without_auth(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """The public workshops page (REQ-WS-*) needs to show what a visitor
    can book without making them sign in first — and must not leak the
    join link, which belongs to someone who has actually booked."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    # The endpoint caps at 12 rows and the dev DB is shared with every
    # previous run of this suite: this file leaves "Executive Coaching
    # Debrief" sessions behind, and test_push's reminder tests leave
    # "Reminder Test Workshop <hex>" sessions starting within 24h — which
    # sort *before* this test's next-Monday session and push it off the
    # list (16 stale rows cancelled by hand on 2026-08-17; recurred by
    # 2026-08-20). Cancel every prior run's leftovers up front so the
    # assertion depends on this run, not on history.
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "UPDATE workshop_sessions SET status = 'cancelled'"
                " WHERE status = 'scheduled'"
                "   AND workshop_id IN (SELECT id FROM workshops"
                "        WHERE title = 'Executive Coaching Debrief'"
                "           OR title LIKE 'Reminder Test Workshop %')"
            )
        )

    starts = _next_weekday_at(1, 9)
    created = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 2,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    # No Authorization header at all.
    public = await client.get("/api/v1/public/workshops")
    assert public.status_code == 200, public.text
    rows = public.json()["items"]
    row = next((r for r in rows if r["session_id"] == session_id), None)
    assert row is not None, "the scheduled session should be publicly listed"
    assert row["capacity"] == 2
    assert row["seats_left"] == 2
    assert row["is_full"] is False
    assert row["duration_minutes"] == 60
    assert "join_url" not in row
    assert "roster" not in row

    # A booking reduces the public seat count.
    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    booked = await client.post(
        f"/api/v1/sessions/{session_id}/book",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert booked.status_code == 200, booked.text
    after = await client.get("/api/v1/public/workshops")
    row = next(r for r in after.json()["items"] if r["session_id"] == session_id)
    assert row["seats_left"] == 1


async def test_cancel_session_cancels_every_booking_notifies_and_audits(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """P7, REQ-WS-03: cancelling a whole session — a gap this codebase
    had zero code path for before this pass — cancels every active
    booking (not just one), not merely the session row itself."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, facilitator_token, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    starts = _next_weekday_at(1, 9)
    session_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 2,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    session_id = session_resp.json()["id"]

    learner_a_token, _, learner_a_email = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    learner_b_token, _, learner_b_email = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    for token in (learner_a_token, learner_b_token):
        booked = await client.post(
            f"/api/v1/sessions/{session_id}/book", headers={"Authorization": f"Bearer {token}"}
        )
        assert booked.status_code == 200, booked.text

    # A stranger cannot cancel this session.
    stranger_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.post(
        f"/api/v1/sessions/{session_id}/cancel",
        json={"reason": "Facilitator is unwell."},
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403

    cancelled = await client.post(
        f"/api/v1/sessions/{session_id}/cancel",
        json={"reason": "Facilitator is unwell."},
        headers={"Authorization": f"Bearer {facilitator_token}"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    roster = await client.get(
        f"/api/v1/sessions/{session_id}/roster",
        headers={"Authorization": f"Bearer {facilitator_token}"},
    )
    rows = {r["email"]: r for r in roster.json()["items"]}
    assert rows[learner_a_email]["booking_status"] == "cancelled"
    assert rows[learner_b_email]["booking_status"] == "cancelled"

    # Cancelling an already-cancelled session is refused, not a silent no-op.
    again = await client.post(
        f"/api/v1/sessions/{session_id}/cancel",
        json={"reason": "Trying again."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert again.status_code == 400

    async with tenant_session_factory(tenant_id) as s:
        audited = (
            await s.execute(
                sa.text(
                    "SELECT action FROM audit_events WHERE entity_id = :sid "
                    "AND action = 'workshop.session.cancelled'"
                ),
                {"sid": session_id},
            )
        ).first()
    assert audited is not None


async def test_multi_facilitator_conflict_check_blocks_co_facilitator_double_booking(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """P7, REQ-WS-02/03: the gap multi-facilitator support needs closed
    — a co-facilitator's *own* conflicts must be checked, not just the
    session's primary facilitator's. Before this pass there was no way
    to add a co-facilitator at all, so this conflict could never even
    be exercised."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_a_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    facilitator_b_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    starts = _next_weekday_at(1, 9)
    session_one = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_a_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert session_one.status_code == 201, session_one.text
    session_one_id = session_one.json()["id"]

    # B joins session one as a co-facilitator, not the primary.
    added = await client.post(
        f"/api/v1/sessions/{session_one_id}/facilitators",
        json={"facilitator_id": facilitator_b_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert added.status_code == 201, added.text
    assert len(added.json()["items"]) == 2

    # A second, overlapping session with B as *primary* must be refused
    # — B is already committed to session one, even though only as a
    # co-facilitator there, not its facilitator_id.
    overlapping = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_b_id,
            "starts_at": (starts + timedelta(minutes=30)).isoformat(),
            "ends_at": (starts + timedelta(hours=1, minutes=30)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert overlapping.status_code == 400, overlapping.text
    assert "already has a session" in overlapping.json()["error"]["message"].lower()

    # Adding B to a *third*, separately-overlapping session is refused
    # the same way, via add_session_facilitator's own conflict check.
    session_three = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_a_id,
            "starts_at": (starts + timedelta(minutes=15)).isoformat(),
            "ends_at": (starts + timedelta(hours=1, minutes=15)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert session_three.status_code == 400, session_three.text

    # Remove the last-remaining facilitator (the primary) is refused —
    # a session must always keep at least one, and the primary can't be
    # removed directly.
    remove_primary = await client.request(
        "DELETE",
        f"/api/v1/sessions/{session_one_id}/facilitators/{facilitator_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert remove_primary.status_code == 400

    # Removing the co-facilitator (not the primary) succeeds.
    remove_co = await client.request(
        "DELETE",
        f"/api/v1/sessions/{session_one_id}/facilitators/{facilitator_b_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert remove_co.status_code == 200, remove_co.text
    assert len(remove_co.json()["items"]) == 1

    # Removing the sole remaining facilitator is refused either way.
    remove_last = await client.request(
        "DELETE",
        f"/api/v1/sessions/{session_one_id}/facilitators/{facilitator_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert remove_last.status_code == 400


async def test_reschedule_moves_booking_and_marks_old_attendance_rescheduled(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """P7 phase 2, REQ-WS-03: reschedule stays cancel-then-rebook (0018's
    own reasoned deferral), but the convenience wrapper marks the old
    booking's attendance "rescheduled" — the enum value that's existed
    unused since 0018 — instead of "cancelled", and GET /bookings (the
    new "my sessions" listing) reflects both sides correctly."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)
    other_workshop_id = await _make_workshop(client, admin_token)

    starts_one = _next_weekday_at(1, 9)
    session_one = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts_one.isoformat(),
            "ends_at": (starts_one + timedelta(hours=1)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert session_one.status_code == 201, session_one.text
    session_one_id = session_one.json()["id"]

    starts_two = _next_weekday_at(1, 10)
    session_two = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts_two.isoformat(),
            "ends_at": (starts_two + timedelta(hours=1)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert session_two.status_code == 201, session_two.text
    session_two_id = session_two.json()["id"]

    # A session on an unrelated workshop, same facilitator's window,
    # non-overlapping with either session above.
    starts_three = _next_weekday_at(1, 11)
    other_session = await client.post(
        f"/api/v1/workshops/{other_workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts_three.isoformat(),
            "ends_at": (starts_three + timedelta(hours=1)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert other_session.status_code == 201, other_session.text
    other_session_id = other_session.json()["id"]

    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    booking = await client.post(
        f"/api/v1/sessions/{session_one_id}/book",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert booking.status_code == 200, booking.text
    booking_id = booking.json()["id"]

    # A stranger cannot reschedule someone else's booking.
    stranger_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.post(
        f"/api/v1/bookings/{booking_id}/reschedule",
        json={"target_session_id": session_two_id},
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403

    # Rescheduling to a session of a *different* workshop is refused.
    cross_workshop = await client.post(
        f"/api/v1/bookings/{booking_id}/reschedule",
        json={"target_session_id": other_session_id},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert cross_workshop.status_code == 400, cross_workshop.text

    rescheduled = await client.post(
        f"/api/v1/bookings/{booking_id}/reschedule",
        json={"target_session_id": session_two_id},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert rescheduled.status_code == 200, rescheduled.text
    new_booking_id = rescheduled.json()["id"]
    assert new_booking_id != booking_id
    assert rescheduled.json()["session_id"] == session_two_id
    assert rescheduled.json()["status"] == "registered"

    async with tenant_session_factory(tenant_id) as s:
        old_attendance = (
            await s.execute(
                sa.text(
                    "SELECT a.status FROM attendance_records a "
                    "JOIN bookings b ON b.id = a.booking_id WHERE b.id = :bid"
                ),
                {"bid": booking_id},
            )
        ).scalar_one()
    assert old_attendance == "rescheduled"

    own_bookings = await client.get(
        "/api/v1/bookings", headers={"Authorization": f"Bearer {learner_token}"}
    )
    assert own_bookings.status_code == 200, own_bookings.text
    rows = {r["booking_id"]: r for r in own_bookings.json()["items"]}
    assert rows[booking_id]["status"] == "cancelled"
    assert rows[booking_id]["can_manage"] is False
    assert rows[new_booking_id]["status"] == "registered"
    assert rows[new_booking_id]["session_id"] == session_two_id
    assert rows[new_booking_id]["can_manage"] is True
    assert rows[new_booking_id]["workshop_title"]
    assert len(rows[new_booking_id]["facilitator_names"]) == 1

    # Rescheduling an already-cancelled booking is refused.
    already_gone = await client.post(
        f"/api/v1/bookings/{booking_id}/reschedule",
        json={"target_session_id": session_one_id},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert already_gone.status_code == 400


async def test_booking_calendar_ics_is_owner_only_and_shaped_correctly(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """P7 phase 3, REQ-WS-05: GET /bookings/{id}/calendar.ics is
    booking-owner-only (the same rule reschedule_booking draws) and
    returns a real text/calendar VEVENT, not just a 200."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    starts = _next_weekday_at(1, 9)
    session_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 3,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    session_id = session_resp.json()["id"]

    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    booking = await client.post(
        f"/api/v1/sessions/{session_id}/book",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    booking_id = booking.json()["id"]

    stranger_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.get(
        f"/api/v1/bookings/{booking_id}/calendar.ics",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert forbidden.status_code == 403

    ics = await client.get(
        f"/api/v1/bookings/{booking_id}/calendar.ics",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert ics.status_code == 200, ics.text
    assert ics.headers["content-type"].startswith("text/calendar")
    text = ics.content.decode("utf-8")
    assert "BEGIN:VEVENT" in text
    assert "STATUS:CONFIRMED" in text
    assert f"UID:{booking_id}@ttli" in text
    assert "Executive Coaching Debrief" in text

    # Cancel the booking, then confirm the ICS reflects the cancellation.
    cancelled = await client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert cancelled.status_code == 204, cancelled.text
    ics_after_cancel = await client.get(
        f"/api/v1/bookings/{booking_id}/calendar.ics",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert "STATUS:CANCELLED" in ics_after_cancel.content.decode("utf-8")


async def test_workshop_credit_purchase_book_cancel_refund_and_exhaustion(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """P7 phase 4: a `requires_credit` workshop only lets a learner book
    while they hold an unspent `workshop_credit` entitlement. Exercises
    the full loop — real EFT purchase, decrement on book, refund on
    cancel, decrement again, then a clean refusal once exhausted —
    against both the HTTP surface and the entitlement row itself, so a
    refusal that happened to be right for the wrong reason (e.g. a
    capacity limit) wouldn't pass this test by accident."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    gated = await client.patch(
        f"/api/v1/workshops/{workshop_id}",
        json={"requires_credit": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert gated.status_code == 200, gated.text
    assert gated.json()["requires_credit"] is True

    product = (
        await client.post(
            "/api/v1/catalogue/products",
            json={
                "slug": f"workshop-credit-{uuid.uuid4().hex[:8]}",
                "name": "Coaching Session Credit",
                "workshop_id": workshop_id,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    price = (
        await client.post(
            f"/api/v1/catalogue/products/{product['id']}/prices",
            json={"currency": "ZAR", "unit_amount": "500.00"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}",
        json={"is_active": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    finance_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    learner_token, learner_id, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    learner_auth = {"Authorization": f"Bearer {learner_token}"}

    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price["id"], "quantity": 1}],
        },
        headers={**learner_auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert order.status_code == 201, order.text
    checkout = await client.post(
        f"/api/v1/orders/{order.json()['id']}/checkout/eft", headers=learner_auth
    )
    assert checkout.status_code == 200, checkout.text
    await client.post(
        f"/api/v1/orders/{order.json()['id']}/payment-proof",
        files={"file": ("proof.txt", b"a real bank transfer receipt", "text/plain")},
        headers=learner_auth,
    )
    approved = await client.post(
        f"/api/v1/payments/{checkout.json()['payment_id']}/approve",
        headers={
            "Authorization": f"Bearer {finance_token}",
            "Idempotency-Key": uuid.uuid4().hex,
        },
    )
    assert approved.status_code == 200, approved.text

    async def _entitlement_quantity() -> int:
        async with tenant_session_factory(tenant_id) as s:
            row = (
                await s.execute(
                    sa.select(Entitlement).where(
                        Entitlement.tenant_id == tenant_id,
                        Entitlement.user_id == learner_id,
                        Entitlement.kind == "workshop_credit",
                        Entitlement.target_id == uuid.UUID(workshop_id),
                    )
                )
            ).scalar_one()
        return row.quantity or 0

    assert await _entitlement_quantity() == 1

    starts = _next_weekday_at(1, 9)

    async def _create_session(offset_hours: int) -> str:
        s = starts + timedelta(hours=offset_hours)
        resp = await client.post(
            f"/api/v1/workshops/{workshop_id}/sessions",
            json={
                "facilitator_id": facilitator_id,
                "starts_at": s.isoformat(),
                "ends_at": (s + timedelta(hours=1)).isoformat(),
                "capacity": 5,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201, resp.text
        return str(resp.json()["id"])

    session_1 = await _create_session(0)
    session_2 = await _create_session(1)
    session_3 = await _create_session(2)

    booking_1 = await client.post(f"/api/v1/sessions/{session_1}/book", headers=learner_auth)
    assert booking_1.status_code == 200, booking_1.text
    assert await _entitlement_quantity() == 0

    refused = await client.post(f"/api/v1/sessions/{session_2}/book", headers=learner_auth)
    assert refused.status_code == 400, refused.text
    assert "credit" in refused.json()["error"]["message"].lower()

    cancelled = await client.post(
        f"/api/v1/bookings/{booking_1.json()['id']}/cancel", headers=learner_auth
    )
    assert cancelled.status_code == 204, cancelled.text
    assert await _entitlement_quantity() == 1

    booking_2 = await client.post(f"/api/v1/sessions/{session_2}/book", headers=learner_auth)
    assert booking_2.status_code == 200, booking_2.text
    assert await _entitlement_quantity() == 0

    refused_again = await client.post(f"/api/v1/sessions/{session_3}/book", headers=learner_auth)
    assert refused_again.status_code == 400, refused_again.text
    assert "credit" in refused_again.json()["error"]["message"].lower()


async def test_booking_without_requires_credit_needs_no_purchase(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Regression pin (P7 phase 4): a workshop that never opts into
    `requires_credit` books exactly as it always did — no product, no
    price, no purchase, straight through to a registered booking."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    facilitator_id, _, _ = await _make_facilitator(
        client, admin_token, tenant_session_factory, crypto, tenant_id=tenant_id
    )
    workshop_id = await _make_workshop(client, admin_token)

    starts = _next_weekday_at(1, 9)
    session_resp = await client.post(
        f"/api/v1/workshops/{workshop_id}/sessions",
        json={
            "facilitator_id": facilitator_id,
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "capacity": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    session_id = session_resp.json()["id"]

    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    booking = await client.post(
        f"/api/v1/sessions/{session_id}/book",
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert booking.status_code == 200, booking.text
    assert booking.json()["status"] == "registered"
