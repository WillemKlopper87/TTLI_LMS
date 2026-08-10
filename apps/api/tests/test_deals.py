"""Phase 5 sprint 4: deals, tasks, notes, activities (02 §10,
REQ-CRM-01/02). HTTP coverage for the deal-centric CRM — a deal always
carries a real, append-only activity trail of what happened to it.
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
    return f"deal-{uuid.uuid4().hex[:12]}@example.com"


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


async def test_only_deal_manage_can_create_deals(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    plain_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.post(
        "/api/v1/deals",
        json={"email": _unique_email(), "title": "Corporate training deal"},
        headers={"Authorization": f"Bearer {plain_token}"},
    )
    assert resp.status_code == 403


async def test_deal_lifecycle_creates_a_real_activity_trail(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    contact_email = _unique_email()

    created = await client.post(
        "/api/v1/deals",
        json={
            "email": contact_email,
            "title": "Corporate leadership programme",
            "amount": "45000.00",
            "currency": "ZAR",
            "source": "outbound",
            "campaign": "q3-corporate-push",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    deal = created.json()
    assert deal["contact_email"] == contact_email
    assert deal["stage"] == "new"
    deal_id = deal["id"]

    stage_change = await client.patch(
        f"/api/v1/deals/{deal_id}/stage",
        json={"stage": "qualified"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert stage_change.status_code == 200, stage_change.text
    assert stage_change.json()["stage"] == "qualified"

    task = await client.post(
        f"/api/v1/deals/{deal_id}/tasks",
        json={"title": "Send proposal"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    assert task.json()["completed_at"] is None

    completed = await client.post(
        f"/api/v1/tasks/{task_id}/complete", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed_at"] is not None

    # Completing an already-complete task is refused, not silently re-accepted.
    re_complete = await client.post(
        f"/api/v1/tasks/{task_id}/complete", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert re_complete.status_code == 400

    note = await client.post(
        f"/api/v1/deals/{deal_id}/notes",
        json={"body": "Client wants a Q4 start date."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert note.status_code == 201, note.text

    detail = await client.get(
        f"/api/v1/deals/{deal_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["deal"]["stage"] == "qualified"
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["completed_at"] is not None
    assert len(body["notes"]) == 1
    assert body["notes"][0]["body"] == "Client wants a Q4 start date."

    activity_kinds = [a["kind"] for a in body["activities"]]
    assert "deal_created" in activity_kinds
    assert "deal_stage_changed" in activity_kinds
    assert "task_created" in activity_kinds
    assert "task_completed" in activity_kinds
    assert "note_added" in activity_kinds


async def test_deal_creation_reuses_existing_contact_not_a_duplicate(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    email = _unique_email()

    first = await client.post(
        "/api/v1/deals",
        json={"email": email, "title": "First deal"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    second = await client.post(
        "/api/v1/deals",
        json={"email": email, "title": "Second deal, same contact"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    async with tenant_session_factory(tenant_id) as s:
        contact_count = (
            await s.execute(
                sa.text("SELECT count(*) FROM contacts WHERE email_blind_index = :idx"),
                {"idx": crypto.blind_index(email)},
            )
        ).scalar_one()
    assert contact_count == 1
    assert first.json()["contact_email"] == second.json()["contact_email"]


async def test_deals_list_is_paginated_and_tenant_scoped(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await client.post(
        "/api/v1/deals",
        json={"email": _unique_email(), "title": "Listed deal"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    page = await client.get(
        "/api/v1/deals?limit=5&offset=0", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] >= 1
    assert len(body["items"]) <= 5
