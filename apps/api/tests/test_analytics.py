"""Payment & Revenue Analytics (`routers/analytics.py`, docs/research/
payment-analytics-dashboard.md §4.3) — the four endpoints
`test_operations.py` never covered (R14, docs/BACKLOG.md): `/revenue-
summary`, `/registrations`, and both CSV twins. `test_operations.py`
already covers `/revenue-series` and the operations overview.

Also `/analytics/podcast-engagement` (R2) — the "Podcast engagement"
panel docs/research/podcast-platform-integration.md §6 asked to be
surfaced once the payment dashboard landed, reading the same
`podcast.*` events `routers/podcasts.py::log_podcast_event` writes.

Same "assert the contract, not an absolute count" discipline
`test_operations.py`'s own docstring states — these are aggregates over
a shared demo tenant other suites also write to, so the invariants
below (totals that must reconcile, arithmetic that must hold) are
pinned instead of specific numbers; the podcast tests use a before/
after delta for the same reason.
"""

from __future__ import annotations

import csv
import io
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
from src.models.event import Event
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
    return f"analytics-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


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


def _parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


async def test_revenue_summary_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    forbidden = await client.get(
        "/api/v1/analytics/revenue-summary", headers={"Authorization": f"Bearer {learner}"}
    )
    assert forbidden.status_code == 403

    anonymous = await client.get("/api/v1/analytics/revenue-summary")
    assert anonymous.status_code == 401


async def test_revenue_summary_arithmetic_holds(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The relationships the service functions promise in their own
    docstrings — real invariants, not incidental values: `total_users`
    is the exact sum of the three buckets, `actual_revenue` is
    `payments_received - refunds_issued` per currency, and
    `predicted_revenue.total` is `pipeline + subscription_renewals`."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    resp = await client.get("/api/v1/analytics/revenue-summary?preset=last_1y", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    pvw = body["paid_vs_waiting"]
    assert pvw["total_users"] == pvw["paid"] + pvw["awaiting_payment"] + pvw["did_not_convert"]

    received = {row["currency"]: float(row["amount"]) for row in body["payments_received"]}
    refunded = {row["currency"]: float(row["amount"]) for row in body["refunds_issued"]}
    net = {row["currency"]: float(row["amount"]) for row in body["actual_revenue"]}
    for currency, amount in net.items():
        assert round(amount, 2) == round(
            received.get(currency, 0.0) - refunded.get(currency, 0.0), 2
        )

    predicted = body["predicted_revenue"]
    pipeline = {row["currency"]: float(row["amount"]) for row in predicted["pipeline"]}
    renewals = {row["currency"]: float(row["amount"]) for row in predicted["subscription_renewals"]}
    total = {row["currency"]: float(row["amount"]) for row in predicted["total"]}
    currencies = set(pipeline) | set(renewals)
    for currency in currencies:
        assert round(total.get(currency, 0.0), 2) == round(
            pipeline.get(currency, 0.0) + renewals.get(currency, 0.0), 2
        )

    # Each provider row is well-formed even if the demo tenant has no
    # payments in the window — an empty list is a valid, tested shape.
    for row in body["payment_methods"]:
        assert row["provider"] in ("card", "eft", "po")
        assert row["payment_count"] >= 0


async def test_registrations_totals_reconcile_with_the_breakdowns(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Every registered user falls into exactly one package label and
    exactly one organisation bucket (`registrations_by_organisation`'s
    own "Other organisations" folding preserves the summed count), so
    both breakdowns must sum to the same headline total."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    resp = await client.get("/api/v1/analytics/registrations?preset=last_1y", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    total = body["total_registered"]
    assert total >= 0
    assert sum(row["user_count"] for row in body["by_package"]) == total
    assert sum(row["user_count"] for row in body["by_organisation"]) == total


async def test_registrations_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)
    resp = await client.get(
        "/api/v1/analytics/registrations", headers={"Authorization": f"Bearer {learner}"}
    )
    assert resp.status_code == 403


async def test_finance_can_read_revenue_and_registrations(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """0028 granted `analytics:view` to finance for exactly this screen."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    headers = {"Authorization": f"Bearer {finance}"}
    assert (
        await client.get("/api/v1/analytics/revenue-summary", headers=headers)
    ).status_code == 200
    assert (await client.get("/api/v1/analytics/registrations", headers=headers)).status_code == 200


async def test_revenue_summary_csv_matches_the_json_report(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """`_csv_response` is built from the *same* aggregation call as the
    JSON route (the router's own module docstring), so the export can
    never drift — this pins that promise rather than trusting it."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    json_resp = await client.get(
        "/api/v1/analytics/revenue-summary?preset=last_1y", headers=headers
    )
    assert json_resp.status_code == 200, json_resp.text
    body = json_resp.json()

    csv_resp = await client.get(
        "/api/v1/analytics/revenue-summary/export.csv?preset=last_1y", headers=headers
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert 'filename="revenue-summary.csv"' in csv_resp.headers["content-disposition"]

    rows = _parse_csv(csv_resp.text)
    assert {r["section"] for r in rows} >= {"period", "paid_vs_waiting", "actual_revenue"}

    pvw_rows = {r["label"]: r["count"] for r in rows if r["section"] == "paid_vs_waiting"}
    assert int(pvw_rows["paid"]) == body["paid_vs_waiting"]["paid"]
    assert int(pvw_rows["total_users"]) == body["paid_vs_waiting"]["total_users"]

    net_json = {row["currency"]: row["amount"] for row in body["actual_revenue"]}
    net_csv = {
        r["currency"]: r["amount"]
        for r in rows
        if r["section"] == "actual_revenue" and r["label"] == "net" and r["currency"]
    }
    for currency, amount in net_json.items():
        assert currency in net_csv
        assert round(float(net_csv[currency]), 2) == round(float(amount), 2)


async def test_revenue_summary_csv_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)
    resp = await client.get(
        "/api/v1/analytics/revenue-summary/export.csv",
        headers={"Authorization": f"Bearer {learner}"},
    )
    assert resp.status_code == 403


async def test_registrations_csv_matches_the_json_report(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    json_resp = await client.get("/api/v1/analytics/registrations?preset=last_1y", headers=headers)
    assert json_resp.status_code == 200, json_resp.text
    body = json_resp.json()

    csv_resp = await client.get(
        "/api/v1/analytics/registrations/export.csv?preset=last_1y", headers=headers
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert 'filename="registrations.csv"' in csv_resp.headers["content-disposition"]

    rows = _parse_csv(csv_resp.text)
    total_row = next(
        r for r in rows if r["section"] == "registrations" and r["label"] == "total_registered"
    )
    assert int(total_row["count"]) == body["total_registered"]

    by_package_csv = sum(
        int(r["count"]) for r in rows if r["section"] == "by_package" and r["count"]
    )
    assert by_package_csv == sum(row["user_count"] for row in body["by_package"])


async def test_registrations_csv_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)
    resp = await client.get(
        "/api/v1/analytics/registrations/export.csv",
        headers={"Authorization": f"Bearer {learner}"},
    )
    assert resp.status_code == 403


async def test_custom_from_to_range_is_honoured_over_a_preset(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """The `preset` XOR `from`+`to` contract (router module docstring) —
    a caller giving explicit bounds gets exactly that window echoed
    back, not the default preset."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    resp = await client.get(
        "/api/v1/analytics/revenue-summary?from=2020-01-01&to=2020-01-31",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200, resp.text
    period = resp.json()["period"]
    assert period["preset"] is None
    assert period["from"].startswith("2020-01-01")
    # Half-open: `to` is exclusive (every service query below uses
    # `< period.end`), so a day-inclusive "to=2020-01-31" resolves to
    # the *next* day's midnight, not the 31st itself.
    assert period["to"].startswith("2020-02-01")


async def _make_and_publish_episode(client, token: str) -> str:
    """Returns the published episode's slug — public event-logging
    addresses episodes by slug, not id."""
    created = await client.post(
        "/api/v1/podcasts",
        json={
            "kind": "curated",
            "title": f"analytics-{uuid.uuid4().hex[:12]}",
            "external_url": "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk",
            "curator_name": "A Guest Host",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201, created.text
    episode_id = created.json()["id"]
    published = await client.post(
        f"/api/v1/podcasts/{episode_id}/publish", headers={"Authorization": f"Bearer {token}"}
    )
    assert published.status_code == 200, published.text
    return str(published.json()["slug"])


async def _podcast_engagement(client, token: str) -> dict:
    resp = await client.get(
        "/api/v1/analytics/podcast-engagement?preset=last_1y",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_podcast_engagement_counts_and_ranks_by_delta(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """A shared demo tenant means absolute counts drift between test
    runs — so a fresh episode is created here and the *delta* this
    test's own events cause is what gets asserted, the same discipline
    `test_operations.py`'s docstring states for its own aggregates."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    slug = await _make_and_publish_episode(client, admin)

    before = await _podcast_engagement(client, admin)

    async def _log(event_name: str) -> None:
        resp = await client.post(
            f"/api/v1/public/podcasts/{slug}/events",
            json={"event_name": event_name},
            headers={"X-Tenant-Host": TENANT_HOST},
        )
        assert resp.status_code == 204, resp.text

    await _log("podcast.episode.viewed")
    await _log("podcast.episode.viewed")
    await _log("podcast.play.started")
    await _log("podcast.play.completed")
    await _log("podcast.embed.click_through")
    # A large, distinctive click count — the leaderboard is capped at
    # the top 5 (TOP_CTA_EPISODE_LIMIT), and this demo tenant's data
    # accumulates across repeated local test runs, each contributing a
    # *different* freshly-created episode. A small count risks getting
    # crowded out by that historical noise; 20 clicks on one episode
    # this run created is not going to be beaten by five other
    # episodes each independently reaching 20+.
    for _ in range(20):
        await _log("podcast.cta.course_clicked")

    after = await _podcast_engagement(client, admin)

    assert after["episode_views"] - before["episode_views"] == 2
    assert after["plays_started"] - before["plays_started"] == 1
    assert after["plays_completed"] - before["plays_completed"] == 1
    assert after["embed_click_throughs"] - before["embed_click_throughs"] == 1
    assert after["cta_clicks"] - before["cta_clicks"] == 20

    top_titles = {row["episode_id"]: row["course_clicks"] for row in after["top_cta_episodes"]}
    assert 20 in top_titles.values(), "this run's episode should rank in the top 5"


async def test_podcast_engagement_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)
    resp = await client.get(
        "/api/v1/analytics/podcast-engagement", headers={"Authorization": f"Bearer {learner}"}
    )
    assert resp.status_code == 403


async def test_podcast_engagement_skips_a_malformed_episode_id_instead_of_500ing(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Overall-review F7: only log_podcast_event writes cta.course_clicked
    rows today, and it always writes a real UUID — but the aggregation
    reads event_properties back out of JSONB with no schema behind it.
    A hand-inserted (or future-writer) row with junk in episode_id must
    degrade the leaderboard by one row, not 500 the whole dashboard."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )

    async with tenant_session_factory(tenant_id) as s:
        s.add(
            Event(
                id=uuid7(),
                tenant_id=tenant_id,
                anonymous_id=uuid7(),
                event_name="podcast.cta.course_clicked",
                event_properties={"episode_id": "not-a-real-uuid"},
                consent_marketing=False,
                consent_analytics=True,
            )
        )

    resp = await client.get(
        "/api/v1/analytics/podcast-engagement?preset=last_1y",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200, resp.text
    # The malformed row is skipped in the leaderboard specifically, not
    # silently dropped from every count — it still counts toward
    # cta_clicks (a plain GROUP BY event_name, no JSONB parsing).
    assert "not-a-real-uuid" not in {
        row["episode_id"] for row in resp.json()["top_cta_episodes"]
    }


async def test_podcast_engagement_csv_matches_the_json_report(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """Overall-review I1: /analytics/podcast-engagement had no CSV
    export, despite the router's own module docstring promising "a CSV
    twin of each" report."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    headers = {"Authorization": f"Bearer {admin}"}

    json_resp = await client.get(
        "/api/v1/analytics/podcast-engagement?preset=last_1y", headers=headers
    )
    assert json_resp.status_code == 200, json_resp.text
    body = json_resp.json()

    csv_resp = await client.get(
        "/api/v1/analytics/podcast-engagement/export.csv?preset=last_1y", headers=headers
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert 'filename="podcast-engagement.csv"' in csv_resp.headers["content-disposition"]

    rows = _parse_csv(csv_resp.text)
    engagement = {r["label"]: r["count"] for r in rows if r["section"] == "engagement"}
    assert int(engagement["episode_views"]) == body["episode_views"]
    assert int(engagement["cta_clicks"]) == body["cta_clicks"]

    csv_titles = {r["label"] for r in rows if r["section"] == "top_cta_episodes"}
    json_titles = {row["title"] for row in body["top_cta_episodes"]}
    assert csv_titles == json_titles


async def test_podcast_engagement_csv_requires_analytics_view(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)
    resp = await client.get(
        "/api/v1/analytics/podcast-engagement/export.csv",
        headers={"Authorization": f"Bearer {learner}"},
    )
    assert resp.status_code == 403
