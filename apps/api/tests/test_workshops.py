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
