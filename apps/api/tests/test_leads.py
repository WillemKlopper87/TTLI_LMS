"""Lead capture (03 §4.1): HTTP coverage, plus raw-SQL checks on the
consent_records and events write paths — the same reason test_rls.py and
test_events.py go around the ORM.
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
    return f"lead-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


def _minimal_body(email: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "email": email,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "privacy_consent": True,
        "marketing_consent": False,
    }
    body.update(overrides)
    return body


async def test_capture_lead_returns_204(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post("/api/v1/leads", json=_minimal_body(_unique_email()))
    assert resp.status_code == 204


async def test_capture_lead_without_privacy_consent_is_rejected(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/v1/leads", json=_minimal_body(_unique_email(), privacy_consent=False)
    )
    assert resp.status_code == 400


async def test_capture_lead_creates_contact_lead_and_consent_row(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()

    resp = await client.post(
        "/api/v1/leads",
        json=_minimal_body(
            email,
            marketing_consent=True,
            utm_source="linkedin",
            utm_campaign="q3-launch",
            company="Acme Corp",
        ),
    )
    assert resp.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        contact_row = (
            await s.execute(
                sa.text("SELECT id, email_domain FROM contacts WHERE email_blind_index = :idx"),
                {"idx": crypto.blind_index(email)},
            )
        ).first()
        assert contact_row is not None
        assert contact_row[1] == "example.com"

        lead_row = (
            await s.execute(
                sa.text(
                    "SELECT utm_source, utm_campaign, company FROM leads WHERE contact_id = :c"
                ),
                {"c": contact_row[0]},
            )
        ).first()
        assert lead_row is not None
        assert lead_row[0] == "linkedin"
        assert lead_row[1] == "q3-launch"
        assert lead_row[2] == "Acme Corp"

        consent_row = (
            await s.execute(
                sa.text("SELECT purpose, granted FROM consent_records WHERE contact_id = :c"),
                {"c": contact_row[0]},
            )
        ).first()
        assert consent_row is not None
        assert consent_row[0] == "marketing"
        assert consent_row[1] is True

        # Sequential test execution (no xdist configured), so the most
        # recent lead.captured row is this request's, not an earlier test's.
        event_row = (
            await s.execute(
                sa.text(
                    "SELECT consent_marketing FROM events WHERE event_name = 'lead.captured' "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).first()
        assert event_row is not None
        assert event_row[0] is True


async def test_capture_lead_twice_updates_progressive_profile_not_duplicate(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()

    first = await client.post("/api/v1/leads", json=_minimal_body(email, company="Acme Corp"))
    assert first.status_code == 204

    second = await client.post("/api/v1/leads", json=_minimal_body(email, job_title="Head of L&D"))
    assert second.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        leads = (
            await s.execute(
                sa.text(
                    "SELECT l.company, l.job_title FROM leads l "
                    "JOIN contacts c ON c.id = l.contact_id "
                    "WHERE c.email_blind_index = :idx"
                ),
                {"idx": crypto.blind_index(email)},
            )
        ).all()
    # Exactly one lead row, carrying fields from both submissions — not two.
    assert len(leads) == 1
    assert leads[0][0] == "Acme Corp"
    assert leads[0][1] == "Head of L&D"


async def test_consent_records_are_append_only(client, tenant_session_factory) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    resp = await client.post("/api/v1/leads", json=_minimal_body(email))
    assert resp.status_code == 204

    async with tenant_session_factory(tenant_id) as s:
        consent_id = (
            await s.execute(sa.text("SELECT id FROM consent_records LIMIT 1"))
        ).scalar_one()
        with pytest.raises(sa.exc.DBAPIError, match="permission denied"):
            await s.execute(
                sa.text("UPDATE consent_records SET granted = true WHERE id = :i"),
                {"i": consent_id},
            )


async def test_login_writes_an_event(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    from src.services import identity

    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    password = "correct horse battery staple 9!"
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(s, crypto, tenant_id=tenant_id, email=email, password=password)

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200

    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text(
                    "SELECT count(*) FROM events WHERE event_name = 'auth.login.succeeded' "
                    "AND created_at > now() - interval '1 minute'"
                )
            )
        ).scalar_one()
    assert count >= 1


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


async def test_list_leads_requires_permission(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    resp = await client.get("/api/v1/leads", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_list_leads_returns_captured_leads(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    resp = await client.post(
        "/api/v1/leads", json=_minimal_body(email, company="Globex", source="podcast")
    )
    assert resp.status_code == 204

    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")

    resp = await client.get(
        "/api/v1/leads",
        params={"limit": 5, "offset": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert body["limit"] == 5
    assert body["offset"] == 0
    match = next((row for row in body["items"] if row["email"] == email), None)
    assert match is not None
    assert match["company"] == "Globex"
    assert match["source"] == "podcast"


async def test_contact_form_message_is_captured_and_visible_to_admin(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Phase 2 close-out: the real /contact page posts here with
    source="contact_form" and a free-text message (0010)."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    email = _unique_email()
    resp = await client.post(
        "/api/v1/leads",
        json=_minimal_body(
            email,
            source="contact_form",
            message="We'd like a quote for 40 seats on the Lead with Intent programme.",
        ),
    )
    assert resp.status_code == 204

    token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin")
    resp = await client.get(
        "/api/v1/leads",
        params={"limit": 5, "offset": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    match = next((row for row in resp.json()["items"] if row["email"] == email), None)
    assert match is not None
    assert match["message"] == "We'd like a quote for 40 seats on the Lead with Intent programme."
    assert match["source"] == "contact_form"
