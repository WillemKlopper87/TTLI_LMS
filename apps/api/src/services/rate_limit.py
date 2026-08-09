"""Redis-backed rate limiting: fixed-window counters.

INCR is atomic, so only the caller who takes a key from 0 to 1 ever sees
count == 1 — that caller sets the window's expiry, and no Lua scripting or
locking is needed to avoid a race on who "owns" setting it.
"""

from __future__ import annotations

from redis.asyncio import Redis


async def hit(redis: Redis, *, key: str, limit: int, window_seconds: int) -> bool:
    """Record one hit against `key`. Returns True while still within `limit`."""
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, window_seconds)
    return count <= limit


__all__ = ["hit"]
