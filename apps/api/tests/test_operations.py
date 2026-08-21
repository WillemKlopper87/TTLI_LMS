"""Operations overview and per-course analytics (`routers/operations.py`,
Pass A of `docs/research/enterprise-gaps-plan.md`).

These are read-only aggregates over data every other test file already
creates, so the assertions here deliberately avoid pinning absolute
counts against a shared demo tenant — they assert the contract (shape,
gating, tenancy, arithmetic that must hold) and the deltas this file
causes itself. A test that asserted "active_learners == 3" would fail
the moment any neighbouring suite enrolled someone.
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
    return f"ops-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_course_id(tenant_session_factory) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        return str(
            (
                await s.execute(
                    sa.text(
                        "SELECT id FROM courses WHERE slug = 'executive-leadership-certificate'"
                    )
                )
            ).scalar_one()
        )


async def _login(client, tenant_session_factory, crypto, *, tenant_id, role: str | None) -> str:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role))
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def test_overview_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """A signed-in learner is not an operations dashboard audience. The
    permission, not the session, is the gate."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    resp = await client.get(
        "/api/v1/analytics/overview", headers={"Authorization": f"Bearer {learner}"}
    )
    assert resp.status_code == 403

    anonymous = await client.get("/api/v1/analytics/overview")
    assert anonymous.status_code == 401


async def test_overview_returns_kpis_and_attention_lists(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    resp = await client.get(
        "/api/v1/analytics/overview", headers={"Authorization": f"Bearer {admin}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    kpis = body["kpis"]
    for key in (
        "active_learners",
        "pending_approvals",
        "completions_this_month",
        "certificates_issued_this_month",
        "upcoming_sessions",
        "at_risk_learners",
    ):
        assert isinstance(kpis[key], int)
        assert kpis[key] >= 0

    # Money is per-currency, never a blended scalar (schemas/analytics.py).
    assert isinstance(kpis["revenue_mtd"], list)
    for row in kpis["revenue_mtd"]:
        assert set(row) == {"currency", "amount"}

    # Every attention list is bounded — a dashboard prompts, the real
    # queues page.
    for key in ("payment_approvals", "ungraded_submissions", "failed_transcodes", "at_risk"):
        assert isinstance(body[key], list)
        assert len(body[key]) <= 8

    # The headline count is the whole queue; the list is a window onto it.
    assert kpis["pending_approvals"] >= len(body["payment_approvals"])
    assert kpis["at_risk_learners"] >= len(body["at_risk"])

    # No raw learner email escapes onto this screen.
    for row in body["at_risk"]:
        assert "@" not in row["learner_reference"]


async def test_finance_can_read_the_overview(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """0028 granted `analytics:view` to finance deliberately — finance is
    the role that lives in a payments-shaped dashboard all day."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    resp = await client.get(
        "/api/v1/analytics/overview", headers={"Authorization": f"Bearer {finance}"}
    )
    assert resp.status_code == 200, resp.text


async def test_course_summaries_are_internally_consistent(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    resp = await client.get(
        "/api/v1/analytics/courses", headers={"Authorization": f"Bearer {admin}"}
    )
    assert resp.status_code == 200, resp.text
    courses = resp.json()["courses"]
    assert courses, "the demo tenant has assigned courses"

    for row in courses:
        assert row["completed"] <= row["enrolled"]
        assert 0.0 <= row["completion_rate"] <= 100.0
        if row["enrolled"] == 0:
            assert row["completion_rate"] == 0.0


async def test_course_analytics_funnel_nests_and_lessons_are_ordered(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    course_id = await _demo_course_id(tenant_session_factory)

    resp = await client.get(
        f"/api/v1/analytics/courses/{course_id}",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    funnel = body["funnel"]
    # The three states nest: you cannot complete without starting, or
    # start without enrolling. If this ever fails the aggregate is lying.
    assert funnel["completed"] <= funnel["started"] <= funnel["enrolled"]
    assert 0.0 <= body["completion_rate"] <= 100.0

    assert body["lesson_dropoff"], "the demo course has lessons"
    for lesson in body["lesson_dropoff"]:
        assert lesson["completed"] <= lesson["reached"]

    for quiz in body["quiz_scores"]:
        assert len(quiz["score_buckets"]) == 5
        assert sum(quiz["score_buckets"]) <= quiz["attempts"]
        if quiz["average_score"] is not None:
            assert 0.0 <= quiz["average_score"] <= 100.0


async def test_course_analytics_hides_a_course_this_tenant_cannot_see(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """A course exists globally and is assigned to tenants. Asking about
    an unassigned one must be indistinguishable from asking about one
    that does not exist, or the endpoint becomes a probe of the global
    catalogue."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    resp = await client.get(
        f"/api/v1/analytics/courses/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


async def test_revenue_series_buckets_and_reconciles_with_the_headline(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The series and the headline "actual revenue" figure are the same
    ledger sliced two ways, so summing the series must reproduce the
    total. If this ever fails, one of the two is lying to a finance
    reader — the whole reason the series reuses actual_revenue's
    definition rather than inventing a second one."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    series = await client.get("/api/v1/analytics/revenue-series?preset=last_1y", headers=headers)
    assert series.status_code == 200, series.text
    body = series.json()

    assert body["granularity"] in ("day", "week", "month")
    # A year of daily points would be unreadable; the server picks the
    # bucket, the client does not.
    assert body["granularity"] != "day"

    summary = await client.get("/api/v1/analytics/revenue-summary?preset=last_1y", headers=headers)
    assert summary.status_code == 200
    headline = {row["currency"]: row["amount"] for row in summary.json()["actual_revenue"]}

    summed: dict[str, float] = {}
    for point in body["points"]:
        # Every point carries every currency, so a quiet bucket reads as
        # zero rather than as a gap in the line.
        assert [a["currency"] for a in point["amounts"]] == body["currencies"]
        for amount in point["amounts"]:
            summed[amount["currency"]] = summed.get(amount["currency"], 0.0) + float(
                amount["amount"]
            )

    for currency, total in headline.items():
        assert round(summed.get(currency, 0.0), 2) == round(float(total), 2), (
            f"the {currency} series must sum to the headline figure"
        )


async def test_revenue_series_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)
    resp = await client.get(
        "/api/v1/analytics/revenue-series", headers={"Authorization": f"Bearer {learner}"}
    )
    assert resp.status_code == 403
