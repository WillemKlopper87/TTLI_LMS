"""Redis connection management. Same init/get/dispose shape as core/db.py,
for the same reason: a module-level singleton the lifespan owns, and tests
create/tear down explicitly per event loop.
"""

from __future__ import annotations

from redis.asyncio import Redis

from src.core.config import Settings

_redis: Redis | None = None


def init_redis(settings: Settings) -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("init_redis() must be called before Redis is requested")
    return _redis


async def dispose_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


__all__ = ["dispose_redis", "get_redis", "init_redis"]
