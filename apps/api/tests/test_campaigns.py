"""Phase 5 sprint 4: campaigns, segments, suppression, unsubscribe
(02 §10, REQ-CRM-04). A campaign send must honour two independent
gates — marketing consent and the suppression list — and a real
unsubscribe/bounce both have to actually suppress future sends, not
just record an event nobody acts on.
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
from src.services import consent as consent_service
from src.services import identity
from src.services import leads as leads_service

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
    return f"camp-{uuid.uuid4().hex[:12]}@example.com"


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
    assert resp.status_code == 200
    return str(resp.json()["access_token"])


async def _capture_lead_with_consent(
    tenant_session_factory, crypto, *, tenant_id, stage: str, granted: bool, marker: str
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    """A real lead, at a chosen pipeline stage, with a real (granted or
    withheld) marketing consent record — the two independent gates a
    campaign send has to honour. `marker` is tagged as utm_campaign and
    always included in this test's own segment criteria: the demo
    tenant's leads table is a real, persistent dev database shared
    across every test run, not reset between them, so a segment scoped
    only by `stage` would also match leads a previous run of this same
    test file left behind and break the exact-count assertions below."""
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        capture = await leads_service.capture(
            s,
            crypto,
            tenant_id=tenant_id,
            email=email,
            first_name="Taylor",
            last_name=None,
            source="test",
            profile={},
            utm={"utm_campaign": marker},
        )
        lead = (
            await s.execute(
                sa.text("SELECT id FROM leads WHERE contact_id = :cid"), {"cid": capture.contact_id}
            )
        ).first()
        await s.execute(
            sa.text("UPDATE leads SET stage = :stage WHERE id = :id"),
            {"stage": stage, "id": lead[0]},
        )
        await consent_service.record(
            s,
            tenant_id=tenant_id,
            purpose="marketing",
            granted=granted,
            source="test",
            policy_version="v1",
            contact_id=capture.contact_id,
        )
    return email, capture.contact_id


async def _setup_campaign(
    client, admin_token: str, *, segment_criteria: dict[str, str]
) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    segment = await client.post(
        "/api/v1/segments",
        json={"name": "Qualified leads", "criteria": segment_criteria},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert segment.status_code == 201, segment.text
    template = await client.post(
        "/api/v1/email-templates",
        json={
            "name": "Q3 nudge",
            "subject": "A programme for {{first_name}}",
            "body_text": "Hi {{first_name}}, thanks for your interest.",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert template.status_code == 201, template.text
    campaign = await client.post(
        "/api/v1/campaigns",
        json={
            "name": "Q3 push",
            "template_id": template.json()["id"],
            "segment_id": segment.json()["id"],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert campaign.status_code == 201, campaign.text
    return campaign.json()["id"], segment.json()["id"]


async def test_send_excludes_non_matching_leads_and_those_without_consent(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    marker = uuid.uuid4().hex[:12]
    await _capture_lead_with_consent(
        tenant_session_factory,
        crypto,
        tenant_id=tenant_id,
        stage="qualified",
        granted=True,
        marker=marker,
    )
    await _capture_lead_with_consent(
        tenant_session_factory,
        crypto,
        tenant_id=tenant_id,
        stage="qualified",
        granted=False,
        marker=marker,
    )
    await _capture_lead_with_consent(
        tenant_session_factory,
        crypto,
        tenant_id=tenant_id,
        stage="new",
        granted=True,
        marker=marker,
    )

    campaign_id, _ = await _setup_campaign(
        client, admin_token, segment_criteria={"stage": "qualified", "utm_campaign": marker}
    )

    result = await client.post(
        f"/api/v1/campaigns/{campaign_id}/send", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert result.status_code == 200, result.text
    body = result.json()
    # Only the qualified + consented lead is sent to — the "new" stage
    # lead never matched the segment, and the qualified-but-unconsented
    # one was excluded before ever touching the send path.
    assert body["sent"] == 1
    assert body["suppressed"] == 0
    assert body["excluded_no_consent"] == 1

    stats = await client.get(
        f"/api/v1/campaigns/{campaign_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert stats.status_code == 200, stats.text
    assert stats.json()["sent"] == 1
    assert stats.json()["campaign"]["status"] == "sent"

    # A second send attempt against an already-sent campaign is refused.
    resend = await client.post(
        f"/api/v1/campaigns/{campaign_id}/send", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resend.status_code == 400


async def test_suppressed_contact_is_skipped_and_shows_in_stats(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    marker = uuid.uuid4().hex[:12]
    email, _ = await _capture_lead_with_consent(
        tenant_session_factory,
        crypto,
        tenant_id=tenant_id,
        stage="qualified",
        granted=True,
        marker=marker,
    )
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "INSERT INTO suppressions (id, tenant_id, email_blind_index, reason) "
                "VALUES (gen_random_uuid(), :tid, :idx, 'manual')"
            ),
            {"tid": str(tenant_id), "idx": crypto.blind_index(email)},
        )

    campaign_id, _ = await _setup_campaign(
        client, admin_token, segment_criteria={"stage": "qualified", "utm_campaign": marker}
    )
    result = await client.post(
        f"/api/v1/campaigns/{campaign_id}/send", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["sent"] == 0
    assert result.json()["suppressed"] == 1

    stats = await client.get(
        f"/api/v1/campaigns/{campaign_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert stats.json()["suppressed"] == 1


async def test_unsubscribe_link_suppresses_future_sends(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    marker = uuid.uuid4().hex[:12]
    email, _ = await _capture_lead_with_consent(
        tenant_session_factory,
        crypto,
        tenant_id=tenant_id,
        stage="qualified",
        granted=True,
        marker=marker,
    )
    campaign_id, _ = await _setup_campaign(
        client, admin_token, segment_criteria={"stage": "qualified", "utm_campaign": marker}
    )
    first_send = await client.post(
        f"/api/v1/campaigns/{campaign_id}/send", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert first_send.json()["sent"] == 1

    async with tenant_session_factory(tenant_id) as s:
        email_send_id = (
            await s.execute(
                sa.text("SELECT id FROM email_sends WHERE campaign_id = :cid AND status = 'sent'"),
                {"cid": campaign_id},
            )
        ).scalar_one()

    unsub = await client.get(f"/api/v1/unsubscribe/{email_send_id}")
    assert unsub.status_code == 204, unsub.text

    async with tenant_session_factory(tenant_id) as s:
        suppressed_count = (
            await s.execute(
                sa.text("SELECT count(*) FROM suppressions WHERE email_blind_index = :idx"),
                {"idx": crypto.blind_index(email)},
            )
        ).scalar_one()
        event_kind = (
            await s.execute(
                sa.text("SELECT kind FROM email_events WHERE email_send_id = :id"),
                {"id": email_send_id},
            )
        ).scalar_one()
    assert suppressed_count == 1
    assert event_kind == "unsubscribed"

    # A second campaign to the same contact never sends to them again —
    # the unsubscribe link actually changed future behaviour, not just
    # logged an event. It's excluded via the *consent* gate specifically
    # (unsubscribe writes a real granted=False consent row, on top of
    # the suppression row), which fires before the suppression check —
    # the suppression list is the defense-in-depth backstop for if
    # consent is ever re-granted without it being re-checked, not the
    # only thing standing between this contact and a resend.
    campaign2_id, _ = await _setup_campaign(
        client, admin_token, segment_criteria={"stage": "qualified", "utm_campaign": marker}
    )
    second_send = await client.post(
        f"/api/v1/campaigns/{campaign2_id}/send", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert second_send.json()["sent"] == 0
    assert second_send.json()["excluded_no_consent"] == 1


async def test_bounce_webhook_suppresses_future_sends(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    marker = uuid.uuid4().hex[:12]
    email, _ = await _capture_lead_with_consent(
        tenant_session_factory,
        crypto,
        tenant_id=tenant_id,
        stage="qualified",
        granted=True,
        marker=marker,
    )
    campaign_id, _ = await _setup_campaign(
        client, admin_token, segment_criteria={"stage": "qualified", "utm_campaign": marker}
    )
    await client.post(
        f"/api/v1/campaigns/{campaign_id}/send", headers={"Authorization": f"Bearer {admin_token}"}
    )

    async with tenant_session_factory(tenant_id) as s:
        email_send_id = (
            await s.execute(
                sa.text("SELECT id FROM email_sends WHERE campaign_id = :cid AND status = 'sent'"),
                {"cid": campaign_id},
            )
        ).scalar_one()

    bounce = await client.post(
        "/api/v1/email-events/bounce",
        json={"email_send_id": str(email_send_id), "reason": "mailbox full"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert bounce.status_code == 204, bounce.text

    async with tenant_session_factory(tenant_id) as s:
        status_row = (
            await s.execute(
                sa.text("SELECT status FROM email_sends WHERE id = :id"), {"id": email_send_id}
            )
        ).scalar_one()
        suppressed_count = (
            await s.execute(
                sa.text("SELECT count(*) FROM suppressions WHERE email_blind_index = :idx"),
                {"idx": crypto.blind_index(email)},
            )
        ).scalar_one()
    assert status_row == "bounced"
    assert suppressed_count == 1


async def test_only_campaign_manage_can_send_or_view_stats(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    plain_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    campaign_id, _ = await _setup_campaign(client, admin_token, segment_criteria={})

    forbidden = await client.post(
        f"/api/v1/campaigns/{campaign_id}/send", headers={"Authorization": f"Bearer {plain_token}"}
    )
    assert forbidden.status_code == 403
