"""Podcast episode authoring, publishing, and public playback
(REQ-STORE-04) — the `podcast:manage` permission gate, the kind-specific
publish/create validation `services/podcasts.py` enforces, that only
`published` episodes are ever visible on the public routes, and that
listen-stat events are logged for a real published episode.
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
    return f"podcast-{uuid.uuid4().hex[:12]}@example.com"


def _unique_title() -> str:
    return f"Test Episode {uuid.uuid4().hex[:8]}"


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


async def _make_curated_episode(client, token: str, *, title: str | None = None) -> str:
    resp = await client.post(
        "/api/v1/podcasts",
        json={
            "kind": "curated",
            "title": title or _unique_title(),
            "external_url": "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk",
            "curator_name": "A Guest Host",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_podcast_authoring_requires_podcast_manage(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.post(
        "/api/v1/podcasts",
        json={"kind": "authored", "title": "Should not be created"},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403


async def test_curated_episode_requires_external_url_and_curator_name(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    resp = await client.post(
        "/api/v1/podcasts",
        json={"kind": "curated", "title": _unique_title()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400, resp.text


async def test_curated_episode_embed_id_is_parsed_from_spotify_url(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    episode_id = await _make_curated_episode(client, admin_token)
    resp = await client.get(
        f"/api/v1/podcasts/{episode_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["external_url"].endswith("4rOoJ6Egrf8K2IrywzwOMk")


async def test_javascript_uri_is_refused_as_external_url(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """external_url is rendered back out as a raw <a href> on the public
    episode page — a javascript:/data: URI must never be accepted, on
    create or on a later edit (apps/web's own defensive scheme check is
    the second layer, not the only one)."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    created = await client.post(
        "/api/v1/podcasts",
        json={
            "kind": "curated",
            "title": _unique_title(),
            "external_url": "javascript:alert(document.cookie)",
            "curator_name": "Someone",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 400, created.text

    episode_id = await _make_curated_episode(client, admin_token)
    updated = await client.patch(
        f"/api/v1/podcasts/{episode_id}",
        json={"external_url": "javascript:alert(1)"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert updated.status_code == 400, updated.text


async def test_authored_episode_cannot_publish_without_audio_or_link(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    created = await client.post(
        "/api/v1/podcasts",
        json={"kind": "authored", "title": _unique_title()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    episode_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/podcasts/{episode_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 400, resp.text


async def test_curated_episode_publishes_and_appears_on_public_listing(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    title = _unique_title()
    episode_id = await _make_curated_episode(client, admin_token, title=title)

    # Not yet published — absent from the public listing.
    before = await client.get("/api/v1/public/podcasts", headers={"X-Tenant-Host": TENANT_HOST})
    assert before.status_code == 200
    assert not any(e["id"] == episode_id for e in before.json()["items"])

    published = await client.post(
        f"/api/v1/podcasts/{episode_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"

    after = await client.get("/api/v1/public/podcasts", headers={"X-Tenant-Host": TENANT_HOST})
    assert after.status_code == 200
    matching = [e for e in after.json()["items"] if e["id"] == episode_id]
    assert len(matching) == 1
    assert matching[0]["title"] == title
    assert matching[0]["curator_name"] == "A Guest Host"


async def test_unpublished_episode_404s_on_the_public_detail_route(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    slug_source = _unique_title()
    created = await client.post(
        "/api/v1/podcasts",
        json={
            "kind": "curated",
            "title": slug_source,
            "external_url": "https://open.spotify.com/episode/0abcDEFghijKLmnop1234",
            "curator_name": "Someone",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    slug = created.json()["slug"]

    resp = await client.get(
        f"/api/v1/public/podcasts/{slug}", headers={"X-Tenant-Host": TENANT_HOST}
    )
    assert resp.status_code == 404


async def test_podcast_event_logging_accepts_known_names_and_rejects_unknown(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    episode_id = await _make_curated_episode(client, admin_token)
    published = await client.post(
        f"/api/v1/podcasts/{episode_id}/publish", headers={"Authorization": f"Bearer {admin_token}"}
    )
    slug = (
        await client.get(
            f"/api/v1/podcasts/{episode_id}", headers={"Authorization": f"Bearer {admin_token}"}
        )
    ).json()["slug"]
    assert published.status_code == 200

    ok = await client.post(
        f"/api/v1/public/podcasts/{slug}/events",
        json={"event_name": "podcast.embed.click_through", "source": "spotify_embed"},
        headers={"X-Tenant-Host": TENANT_HOST},
    )
    assert ok.status_code == 204, ok.text

    rejected = await client.post(
        f"/api/v1/public/podcasts/{slug}/events",
        json={"event_name": "not.a.real.event"},
        headers={"X-Tenant-Host": TENANT_HOST},
    )
    assert rejected.status_code == 404


async def test_spotify_lookup_reports_not_configured_with_no_credentials(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    resp = await client.get(
        "/api/v1/podcasts/spotify-lookup",
        params={"url": "https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["configured"] is False


async def test_kind_cannot_be_changed_after_creation(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    episode_id = await _make_curated_episode(client, admin_token)
    resp = await client.patch(
        f"/api/v1/podcasts/{episode_id}",
        json={"title": "Renamed", "kind": "authored"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    # kind isn't in PodcastEpisodeUpdateRequest at all — a smuggled field
    # is simply ignored by Pydantic, the same "no way to set it" guarantee
    # test_lesson_update_has_no_way_to_set_activity_type_or_quiz_id checks.
    assert resp.json()["kind"] == "curated"
    assert resp.json()["title"] == "Renamed"


async def test_admin_listing_includes_drafts_public_listing_does_not(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    episode_id = await _make_curated_episode(client, admin_token)

    admin_listing = await client.get(
        "/api/v1/podcasts", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert admin_listing.status_code == 200
    items = admin_listing.json()["items"]
    assert any(e["id"] == episode_id for e in items)
    assert any(e["state"] == "draft" for e in items if e["id"] == episode_id)

    public_listing = await client.get(
        "/api/v1/public/podcasts", headers={"X-Tenant-Host": TENANT_HOST}
    )
    assert not any(e["id"] == episode_id for e in public_listing.json()["items"])
