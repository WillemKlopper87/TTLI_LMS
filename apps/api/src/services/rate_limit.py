"""Redis-backed rate limiting: fixed-window counters.

INCR is atomic; EXPIRE NX on every hit sets the window only when the key has
no TTL yet. That heals the crash window between a first INCR and its EXPIRE —
whichever hit comes next re-arms the expiry instead of the key living forever
at its counted value. Fixed windows allow up to 2x the limit across a window
boundary; accepted, the spec's limits have that headroom.
"""

from __future__ import annotations

from redis.asyncio import Redis


async def hit(redis: Redis, *, key: str, limit: int, window_seconds: int) -> bool:
    """Record one hit against `key`. Returns True while still within `limit`."""
    count = int(await redis.incr(key))
    await redis.expire(key, window_seconds, nx=True)
    return count <= limit


__all__ = ["hit"]
