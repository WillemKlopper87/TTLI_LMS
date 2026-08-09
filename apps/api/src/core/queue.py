"""arq job-queue connection management. Same init/get/dispose shape as
core/db.py and core/redis.py — a module-level singleton the lifespan owns.

Separate from core/redis.py deliberately: that module hands out a plain
`redis.asyncio.Redis` for caching and rate limiting, this one hands out an
`ArqRedis` for enqueueing jobs the worker (src/workers/main.py) processes.
Same physical Redis, different client, different purpose.
"""

from __future__ import annotations

from arq.connections import ArqRedis, RedisSettings, create_pool

from src.core.config import Settings

_queue: ArqRedis | None = None


async def init_queue(settings: Settings) -> ArqRedis:
    global _queue
    if _queue is None:
        _queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _queue


def get_queue() -> ArqRedis:
    if _queue is None:
        raise RuntimeError("init_queue() must be called before the queue is requested")
    return _queue


async def dispose_queue() -> None:
    global _queue
    if _queue is not None:
        await _queue.aclose()
    _queue = None


__all__ = ["dispose_queue", "get_queue", "init_queue"]
