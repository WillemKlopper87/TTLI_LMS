"""The maintenance jobs, run exactly as the worker runs them: through the
SECURITY DEFINER functions, over an app_user connection with no tenant bound.
That combination is the point — the jobs must work despite RLS and without
DDL privileges of their own.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
import pytest
import sqlalchemy as sa
from src.core.config import Settings, get_settings
from src.core.db import dispose_engine, init_engine
from src.core.ids import uuid7
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.models.auth import RefreshToken
from src.models.push import PushSubscription
from src.models.workshop import Booking, Facilitator, Workshop, WorkshopSession
from src.services import identity
from src.services import push as push_service
from src.services.email import send_sync
from src.workers.main import (
    downgrade_expired_guests,
    extend_event_partitions,
    purge_expired_auth,
    revoke_lapsed_subscriptions,
    send_email_job,
    send_push_job,
    send_workshop_reminders,
)

pytestmark = pytest.mark.integration


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
async def queue(settings):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip(
            "no Redis on the configured REDIS_URL — run: "
            "docker compose -f infra/docker-compose.yml up -d redis"
        )
    redis = init_redis(settings)
    await redis.flushdb()
    await init_queue(settings)
    yield
    await dispose_redis()
    await dispose_queue()


# infra/docker-compose.yml runs Mailpit, not MailHog (docstring there has
# the Trivy-scan reasoning) — its own /api/v1 shape, not MailHog's
# /api/v2 one. Verified against a real captured message, not assumed:
# `To` is a list of {Name, Address} objects and `Subject` is a plain
# string, not MailHog's nested `Content.Headers` shape.
MAILPIT_API = "http://localhost:8145/api/v1"


@pytest.fixture
async def engine(settings, database_url):  # type: ignore[no-untyped-def]
    init_engine(settings)
    yield
    await dispose_engine()


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def test_extend_event_partitions_is_idempotent_and_extends(
    engine, tenant_session_factory
) -> None:  # type: ignore[no-untyped-def]
    created_first = await extend_event_partitions({})
    # 0004 already bootstrapped ~13 months, so a second run creates nothing.
    created_second = await extend_event_partitions({})
    assert created_second == 0
    assert created_first >= 0

    async with tenant_session_factory(None) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'events'::regclass")
            )
        ).scalar_one()
    assert count >= 13


async def test_purge_deletes_only_rows_past_the_grace_period(
    engine, tenant_session_factory
) -> None:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        tenant_id = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))
        ).scalar_one()

    now = datetime.now(UTC)
    old_hash = uuid.uuid4().bytes + uuid.uuid4().bytes  # 32 unique bytes
    fresh_hash = uuid.uuid4().bytes + uuid.uuid4().bytes

    async with tenant_session_factory(tenant_id) as s:
        user_id = (await s.execute(sa.text("SELECT id FROM users LIMIT 1"))).scalar_one()
        s.add(
            RefreshToken(
                tenant_id=tenant_id,
                user_id=user_id,
                family_id=uuid.uuid4(),
                token_hash=old_hash,
                expires_at=now - timedelta(days=40),
            )
        )
        s.add(
            RefreshToken(
                tenant_id=tenant_id,
                user_id=user_id,
                family_id=uuid.uuid4(),
                token_hash=fresh_hash,
                expires_at=now + timedelta(days=1),
            )
        )

    purged = await purge_expired_auth({})
    assert purged >= 1

    async with tenant_session_factory(tenant_id) as s:
        remaining = (
            (
                await s.execute(
                    sa.text("SELECT token_hash FROM refresh_tokens WHERE token_hash IN (:a, :b)"),
                    {"a": old_hash, "b": fresh_hash},
                )
            )
            .scalars()
            .all()
        )
    assert old_hash not in remaining
    assert fresh_hash in remaining


async def test_send_email_job_delivers_via_smtp() -> None:  # type: ignore[no-untyped-def]
    """Real delivery to Mailpit (infra/docker-compose.yml, also a CI
    service container — see api.yml) rather than a mock: this is the one
    place that would silently rot if a settings rename or an SMTP-library
    upgrade broke the actual wire call, since services/email.py never
    exercises it inline anymore."""
    marker = uuid.uuid4().hex[:12]
    to = f"worker-test-{marker}@example.com"
    subject = f"arq worker test {marker}"

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{MAILPIT_API}/messages")
    except httpx.ConnectError:
        pytest.skip("Mailpit is not reachable at :8145 — docker compose up -d mailhog")
    if resp.status_code != 200:
        pytest.skip("Mailpit is not reachable at :8145 — docker compose up -d mailhog")

    await send_email_job({}, to=to, subject=subject, body="hello from the worker")

    async with httpx.AsyncClient() as http:
        messages = (await http.get(f"{MAILPIT_API}/messages")).json()["messages"]
    assert any(
        m["Subject"] == subject and any(addr["Address"] == to for addr in m["To"]) for m in messages
    )


async def test_revoke_lapsed_subscriptions_respects_grace_period(
    engine, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        tenant_id = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))
        ).scalar_one()

    async with tenant_session_factory(tenant_id) as s:
        plan_id = (
            await s.execute(
                sa.text("SELECT id FROM subscription_plans WHERE tenant_id = :t LIMIT 1"),
                {"t": tenant_id},
            )
        ).scalar_one()
        course_id = (
            await s.execute(
                sa.text("SELECT id FROM courses WHERE slug = 'executive-leadership-certificate'")
            )
        ).scalar_one()
        lapsed_user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=f"lapsed-{uuid.uuid4().hex[:10]}@example.com"
        )
        fresh_user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=f"fresh-{uuid.uuid4().hex[:10]}@example.com"
        )

    now = datetime.now(UTC)
    # 3-day default grace: 5 days past period_end is lapsed, 1 day past is not.
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "INSERT INTO subscriptions "
                "(id, tenant_id, user_id, plan_id, status, current_period_start, "
                "current_period_end) VALUES (:id, :t, :u, :p, 'active', :start, :end)"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "u": lapsed_user.id,
                "p": plan_id,
                "start": now - timedelta(days=35),
                "end": now - timedelta(days=5),
            },
        )
        await s.execute(
            sa.text(
                "INSERT INTO subscriptions "
                "(id, tenant_id, user_id, plan_id, status, current_period_start, "
                "current_period_end) VALUES (:id, :t, :u, :p, 'active', :start, :end)"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "u": fresh_user.id,
                "p": plan_id,
                "start": now - timedelta(days=29),
                "end": now + timedelta(days=1),
            },
        )
        # A lapsed-with-grace-baked-in entitlement (services/subscriptions.py's
        # GRACE_DAYS convention: expires_at already includes it) and an
        # unexpired one.
        lapsed_entitlement_id = uuid.uuid4()
        fresh_entitlement_id = uuid.uuid4()
        onetime_entitlement_id = uuid.uuid4()
        for eid, user_id, expires_at in (
            (lapsed_entitlement_id, lapsed_user.id, now - timedelta(hours=1)),
            (fresh_entitlement_id, fresh_user.id, now + timedelta(days=10)),
            (onetime_entitlement_id, lapsed_user.id, None),
        ):
            await s.execute(
                sa.text(
                    "INSERT INTO entitlements "
                    "(id, tenant_id, user_id, kind, target_id, granted_at, expires_at) "
                    "VALUES (:id, :t, :u, 'course', :c, now(), :e)"
                ),
                {"id": eid, "t": tenant_id, "u": user_id, "c": course_id, "e": expires_at},
            )

    revoked = await revoke_lapsed_subscriptions({})
    assert revoked >= 1

    async with tenant_session_factory(tenant_id) as s:
        lapsed_status = (
            await s.execute(
                sa.text("SELECT status FROM subscriptions WHERE user_id = :u"),
                {"u": lapsed_user.id},
            )
        ).scalar_one()
        fresh_status = (
            await s.execute(
                sa.text("SELECT status FROM subscriptions WHERE user_id = :u"), {"u": fresh_user.id}
            )
        ).scalar_one()
        revoked_ats = dict(
            (
                await s.execute(
                    sa.text("SELECT id, revoked_at FROM entitlements WHERE id IN (:a, :b, :c)"),
                    {
                        "a": lapsed_entitlement_id,
                        "b": fresh_entitlement_id,
                        "c": onetime_entitlement_id,
                    },
                )
            ).all()
        )
    assert lapsed_status == "cancelled"
    assert fresh_status == "active"
    assert revoked_ats[lapsed_entitlement_id] is not None
    assert revoked_ats[fresh_entitlement_id] is None
    # One-time purchases (expires_at IS NULL) are never touched by the sweep.
    assert revoked_ats[onetime_entitlement_id] is None


async def test_downgrade_expired_guests_leaves_active_and_non_guests_alone(
    engine, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        tenant_id = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))
        ).scalar_one()

    async with tenant_session_factory(tenant_id) as s:
        expired_guest = await identity.create_user(
            s,
            crypto,
            tenant_id=tenant_id,
            email=f"expired-guest-{uuid.uuid4().hex[:10]}@example.com",
            is_guest=True,
            guest_days=-1,
        )
        active_guest = await identity.create_user(
            s,
            crypto,
            tenant_id=tenant_id,
            email=f"active-guest-{uuid.uuid4().hex[:10]}@example.com",
            is_guest=True,
            guest_days=7,
        )
        non_guest = await identity.create_user(
            s,
            crypto,
            tenant_id=tenant_id,
            email=f"non-guest-{uuid.uuid4().hex[:10]}@example.com",
        )

    downgraded = await downgrade_expired_guests({})
    assert downgraded >= 1

    async with tenant_session_factory(tenant_id) as s:
        statuses = dict(
            (
                await s.execute(
                    sa.text("SELECT id, status FROM users WHERE id IN (:a, :b, :c)"),
                    {"a": expired_guest.id, "b": active_guest.id, "c": non_guest.id},
                )
            ).all()
        )
    assert statuses[expired_guest.id] == "expired"
    assert statuses[active_guest.id] == "active"
    assert statuses[non_guest.id] == "active"

    # Idempotent: a second run finds nothing new to transition.
    assert await downgrade_expired_guests({}) == 0


async def test_send_push_job_deletes_subscription_on_gone(
    monkeypatch, engine, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=f"pushjob-{uuid.uuid4().hex[:10]}@example.com"
        )
        subscription = PushSubscription(
            id=uuid7(),
            tenant_id=tenant_id,
            user_id=user.id,
            endpoint=f"https://push.example.com/{uuid.uuid4().hex}",
            p256dh_key="k",
            auth_key="a",
        )
        s.add(subscription)
        subscription_id = subscription.id

    def _fake_send_push_sync(settings, **kwargs):  # type: ignore[no-untyped-def]
        raise push_service.PushSubscriptionGone("gone")

    monkeypatch.setattr(push_service, "send_push_sync", _fake_send_push_sync)

    result = await send_push_job(
        {},
        tenant_id=str(tenant_id),
        subscription_id=str(subscription_id),
        title="t",
        body="b",
        url=None,
    )
    assert result is False

    async with tenant_session_factory(tenant_id) as s:
        remaining = (
            await s.execute(
                sa.text("SELECT count(*) FROM push_subscriptions WHERE id = :i"),
                {"i": subscription_id},
            )
        ).scalar_one()
    assert remaining == 0


async def test_send_push_job_keeps_subscription_on_success(
    monkeypatch, engine, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=f"pushjob-{uuid.uuid4().hex[:10]}@example.com"
        )
        subscription = PushSubscription(
            id=uuid7(),
            tenant_id=tenant_id,
            user_id=user.id,
            endpoint=f"https://push.example.com/{uuid.uuid4().hex}",
            p256dh_key="k",
            auth_key="a",
        )
        s.add(subscription)
        subscription_id = subscription.id

    calls = []
    monkeypatch.setattr(
        push_service, "send_push_sync", lambda settings, **kwargs: calls.append(kwargs)
    )

    result = await send_push_job(
        {},
        tenant_id=str(tenant_id),
        subscription_id=str(subscription_id),
        title="t",
        body="b",
        url="/learn",
    )
    assert result is True
    assert len(calls) == 1

    async with tenant_session_factory(tenant_id) as s:
        remaining = (
            await s.execute(
                sa.text("SELECT count(*) FROM push_subscriptions WHERE id = :i"),
                {"i": subscription_id},
            )
        ).scalar_one()
    assert remaining == 1


async def test_send_workshop_reminders_only_notifies_sessions_in_window_once(
    engine, queue, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    now = datetime.now(UTC)

    async with tenant_session_factory(tenant_id) as s:
        facilitator_user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=f"facilitator-{uuid.uuid4().hex[:10]}@example.com"
        )
        learner_email = f"reminder-learner-{uuid.uuid4().hex[:10]}@example.com"
        learner = await identity.create_user(s, crypto, tenant_id=tenant_id, email=learner_email)
        far_future_learner = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=f"far-learner-{uuid.uuid4().hex[:10]}@example.com"
        )

    async with tenant_session_factory(tenant_id) as s:
        facilitator = Facilitator(id=uuid7(), tenant_id=tenant_id, user_id=facilitator_user.id)
        s.add(facilitator)
        await s.flush()

        workshop = Workshop(
            id=uuid7(),
            tenant_id=tenant_id,
            title=f"Reminder Test Workshop {uuid.uuid4().hex[:6]}",
            session_type="group_workshop",
        )
        s.add(workshop)
        await s.flush()

        due_session = WorkshopSession(
            id=uuid7(),
            tenant_id=tenant_id,
            workshop_id=workshop.id,
            facilitator_id=facilitator.id,
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=3),
            capacity=10,
        )
        far_session = WorkshopSession(
            id=uuid7(),
            tenant_id=tenant_id,
            workshop_id=workshop.id,
            facilitator_id=facilitator.id,
            starts_at=now + timedelta(days=10),
            ends_at=now + timedelta(days=10, hours=1),
            capacity=10,
        )
        s.add_all([due_session, far_session])
        await s.flush()

        s.add(
            Booking(id=uuid7(), tenant_id=tenant_id, session_id=due_session.id, user_id=learner.id)
        )
        s.add(
            Booking(
                id=uuid7(),
                tenant_id=tenant_id,
                session_id=far_session.id,
                user_id=far_future_learner.id,
            )
        )

    reminded = await send_workshop_reminders({})
    assert reminded >= 1

    async with tenant_session_factory(tenant_id) as s:
        due_reminder_sent_at = (
            await s.execute(
                sa.text("SELECT reminder_sent_at FROM bookings WHERE session_id = :sid"),
                {"sid": due_session.id},
            )
        ).scalar_one()
        far_reminder_sent_at = (
            await s.execute(
                sa.text("SELECT reminder_sent_at FROM bookings WHERE session_id = :sid"),
                {"sid": far_session.id},
            )
        ).scalar_one()
    assert due_reminder_sent_at is not None
    assert far_reminder_sent_at is None

    # Idempotent: a second run finds nothing new in the due session
    # (already reminded) and nothing yet in the far one (still outside
    # the window).
    second_run = await send_workshop_reminders({})
    assert second_run == 0


def test_send_sync_raises_on_unreachable_smtp_host() -> None:
    """The failure mode arq's retry (max_tries=5, WorkerSettings) depends on:
    send_sync must raise, not swallow, so a transient SMTP outage becomes a
    retried job instead of a silently dropped email."""
    base = get_settings()
    unreachable = Settings(
        database_url=base.database_url,
        database_url_sync=base.database_url_sync,
        app_db_password=base.app_db_password,
        field_encryption_key=base.field_encryption_key,
        blind_index_key=base.blind_index_key,
        smtp_host="127.0.0.1",
        smtp_port=1,  # nothing listens here
    )
    with pytest.raises(OSError):
        send_sync(unreachable, to="a@example.com", subject="x", body="x")
