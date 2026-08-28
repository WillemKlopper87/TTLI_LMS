"""services/rate_limit.py's route classes (report M8).

The important claim to prove isn't "hit() counts correctly" (that's
already exercised indirectly by every existing per-endpoint rate-limit
test) -- it's that a route class actually gates a real route through
`Depends(rate_limited(...))`, and that a previously-uncovered `/public/*`
read endpoint (the exact gap the report named) now has a real ceiling
where it had none at all before this pass.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"


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


async def test_a_public_read_endpoint_that_had_no_limit_before_now_has_one(client) -> None:  # type: ignore[no-untyped-def]
    """`/public/recommendations` (like every other public browse/detail
    route) carried no rate limit at all before this pass -- the exact gap
    report M8 names. 300 requests is PUBLIC_READ's real production limit,
    not a test-only stand-in, so this proves the actual ceiling, not an
    approximation of it."""
    for _ in range(300):
        resp = await client.get("/api/v1/public/recommendations")
        assert resp.status_code == 200, resp.text

    over_limit = await client.get("/api/v1/public/recommendations")
    assert over_limit.status_code == 429, over_limit.text
    assert over_limit.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


async def test_public_read_budget_is_shared_across_endpoints_not_per_route(client) -> None:  # type: ignore[no-untyped-def]
    """PUBLIC_READ is deliberately one shared counter across the whole
    public catalogue surface (services/rate_limit.py's own reasoning: a
    scraper spreading requests across courses/podcasts/articles/paths/
    workshops must not get N times the intended rate for free). Split
    close to evenly across two different public-read routes and confirm
    the combined total -- not either route's own count -- is what trips
    the limit."""
    for _ in range(150):
        resp = await client.get("/api/v1/public/recommendations")
        assert resp.status_code == 200, resp.text
    for _ in range(150):
        resp = await client.get("/api/v1/public/learning-paths")
        assert resp.status_code == 200, resp.text

    over_limit = await client.get("/api/v1/public/recommendations")
    assert over_limit.status_code == 429, over_limit.text


async def test_engagement_event_budgets_stay_independent_per_content_type(client) -> None:  # type: ignore[no-untyped-def]
    """Unlike PUBLIC_READ, ARTICLE_EVENTS and PODCAST_EVENTS are two
    separate counters on purpose (services/rate_limit.py's own reasoning:
    a burst of article reads must not spend a visitor's podcast-play
    budget). Exhausting one must not touch the other."""
    from src.core.redis import get_redis
    from src.services import rate_limit

    redis = get_redis()
    fake_ip = f"203.0.113.{uuid.uuid4().int % 250}"
    for _ in range(rate_limit.ARTICLE_EVENTS.limit):
        ok = await rate_limit.hit(
            redis,
            key=f"ratelimit:{rate_limit.ARTICLE_EVENTS.key_prefix}:ip:{fake_ip}",
            limit=rate_limit.ARTICLE_EVENTS.limit,
            window_seconds=rate_limit.ARTICLE_EVENTS.window_seconds,
        )
        assert ok

    article_exhausted = await rate_limit.hit(
        redis,
        key=f"ratelimit:{rate_limit.ARTICLE_EVENTS.key_prefix}:ip:{fake_ip}",
        limit=rate_limit.ARTICLE_EVENTS.limit,
        window_seconds=rate_limit.ARTICLE_EVENTS.window_seconds,
    )
    assert not article_exhausted

    podcast_still_ok = await rate_limit.hit(
        redis,
        key=f"ratelimit:{rate_limit.PODCAST_EVENTS.key_prefix}:ip:{fake_ip}",
        limit=rate_limit.PODCAST_EVENTS.limit,
        window_seconds=rate_limit.PODCAST_EVENTS.window_seconds,
    )
    assert podcast_still_ok
