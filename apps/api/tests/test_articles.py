"""Article authoring and public reading (`docs/research/resources-hub-
design.md` §2) — the `podcast:manage` permission gate (reused, not a new
permission — see `0030`'s migration docstring), that publish refuses an
empty body and computes `reading_minutes`, and that only `published`
articles are ever visible on the public routes.
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
    return f"article-{uuid.uuid4().hex[:12]}@example.com"


def _unique_title() -> str:
    return f"Test Article {uuid.uuid4().hex[:8]}"


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


async def _make_article(
    client, token: str, *, title: str | None = None, body: str = "Word " * 250
) -> str:
    resp = await client.post(
        "/api/v1/articles",
        json={
            "title": title or _unique_title(),
            "dek": "A one-line summary.",
            "body": body,
            "author_name": "A Facilitator",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_article_authoring_requires_podcast_manage(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.post(
        "/api/v1/articles",
        json={"title": "Should not be created", "body": "Some text."},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403


async def test_article_cannot_publish_with_blank_body(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    created = await client.post(
        "/api/v1/articles",
        json={"title": _unique_title(), "body": "   "},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    article_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/articles/{article_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 400, resp.text


async def test_article_publishes_computes_reading_minutes_and_appears_on_public_listing(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    title = _unique_title()
    # 400 words at the 200wpm heuristic -> 2 minutes.
    article_id = await _make_article(client, admin_token, title=title, body="Word " * 400)

    before = await client.get("/api/v1/public/articles", headers={"X-Tenant-Host": TENANT_HOST})
    assert before.status_code == 200
    assert not any(a["id"] == article_id for a in before.json()["items"])

    published = await client.post(
        f"/api/v1/articles/{article_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"
    assert published.json()["reading_minutes"] == 2
    assert published.json()["published_at"] is not None

    after = await client.get("/api/v1/public/articles", headers={"X-Tenant-Host": TENANT_HOST})
    assert after.status_code == 200
    matching = [a for a in after.json()["items"] if a["id"] == article_id]
    assert len(matching) == 1
    assert matching[0]["title"] == title
    assert matching[0]["author_name"] == "A Facilitator"


async def test_unpublished_article_404s_on_the_public_detail_route(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    created = await client.post(
        "/api/v1/articles",
        json={"title": _unique_title(), "body": "Some unpublished text."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    slug = created.json()["slug"]

    resp = await client.get(
        f"/api/v1/public/articles/{slug}", headers={"X-Tenant-Host": TENANT_HOST}
    )
    assert resp.status_code == 404


async def test_unpublishing_an_article_removes_it_from_the_public_listing(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    article_id = await _make_article(client, admin_token)
    await client.post(
        f"/api/v1/articles/{article_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    await client.post(
        f"/api/v1/articles/{article_id}/unpublish",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    after = await client.get("/api/v1/public/articles", headers={"X-Tenant-Host": TENANT_HOST})
    assert not any(a["id"] == article_id for a in after.json()["items"])


async def test_article_view_event_accepts_viewed_rejects_unknown_and_unpublished(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """R3: "at least a viewed event for symmetry" with podcasts' six —
    the exact contract the frontend's `ArticleViewTracker` client leaf
    relies on, mirroring `test_podcasts.py`'s own event-logging test."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    article_id = await _make_article(client, admin_token)
    slug = (
        await client.get(
            f"/api/v1/articles/{article_id}", headers={"Authorization": f"Bearer {admin_token}"}
        )
    ).json()["slug"]

    # Not yet published — the event endpoint reuses get_published_article,
    # so it 404s the same way the public detail route already does.
    unpublished = await client.post(
        f"/api/v1/public/articles/{slug}/events",
        json={"event_name": "article.viewed"},
        headers={"X-Tenant-Host": TENANT_HOST},
    )
    assert unpublished.status_code == 404

    await client.post(
        f"/api/v1/articles/{article_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )

    ok = await client.post(
        f"/api/v1/public/articles/{slug}/events",
        json={"event_name": "article.viewed"},
        headers={"X-Tenant-Host": TENANT_HOST},
    )
    assert ok.status_code == 204, ok.text

    rejected = await client.post(
        f"/api/v1/public/articles/{slug}/events",
        json={"event_name": "not.a.real.event"},
        headers={"X-Tenant-Host": TENANT_HOST},
    )
    assert rejected.status_code == 404


async def test_article_event_logging_is_rate_limited_per_ip(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """Overall-review F5, the article twin of test_podcasts.py's own
    rate-limit test — this endpoint had no rate limit at all before
    this pass."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    article_id = await _make_article(client, admin_token)
    slug = (
        await client.get(
            f"/api/v1/articles/{article_id}", headers={"Authorization": f"Bearer {admin_token}"}
        )
    ).json()["slug"]
    await client.post(
        f"/api/v1/articles/{article_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )

    for _ in range(60):
        resp = await client.post(
            f"/api/v1/public/articles/{slug}/events",
            json={"event_name": "article.viewed"},
            headers={"X-Tenant-Host": TENANT_HOST},
        )
        assert resp.status_code == 204, resp.text

    over_limit = await client.post(
        f"/api/v1/public/articles/{slug}/events",
        json={"event_name": "article.viewed"},
        headers={"X-Tenant-Host": TENANT_HOST},
    )
    assert over_limit.status_code == 429, over_limit.text
