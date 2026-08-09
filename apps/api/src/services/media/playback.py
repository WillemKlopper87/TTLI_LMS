"""Signed HLS playback (03 §6.7, 06 §3.5, REQ-BYPASS-09).

Media players cannot set headers on segment sub-requests (06 §3.2's
inherited constraint from Streaming_Server's `auth.js`), so the access
token travels as a query parameter instead. `GET /media/{id}/hls/{file}`
serves every manifest with its internal relative references rewritten to
carry that same token — that is what makes segment and init-segment
requests resolve without ever presenting an Authorization header.

Tokens are Redis-backed, short-lived, and re-minted per playback attempt
rather than cached — a revoked entitlement takes effect on the very next
mint, not whenever a cached token happens to expire.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid

from redis.asyncio import Redis

_TOKEN_PREFIX = "playback:token:"  # noqa: S105 - a Redis key prefix, not a credential
_SESSION_SET_PREFIX = "playback:sessions:"
_MAP_URI_RE = re.compile(r'(#EXT-X-MAP:URI=")([^"]+)(")')


async def mint(
    redis: Redis,
    *,
    user_id: uuid.UUID,
    video_asset_id: uuid.UUID,
    expires_in: int,
    max_concurrent_sessions: int,
) -> str:
    """Issues a token and enforces the concurrent-session cap
    (REQ-BYPASS-09) by terminating the oldest session beyond it — the
    newest request is the one actually in front of a person right now,
    so it is the new session that wins, not the old one."""
    token = secrets.token_urlsafe(32)
    sessions_key = f"{_SESSION_SET_PREFIX}{user_id}"

    await redis.zadd(sessions_key, {token: time.time()})
    await redis.expire(sessions_key, expires_in)

    excess = int(await redis.zcard(sessions_key)) - max_concurrent_sessions
    if excess > 0:
        oldest = await redis.zrange(sessions_key, 0, excess - 1)
        if oldest:
            await redis.zrem(sessions_key, *oldest)
            # decode_responses=True on this client (core/redis.py) — every
            # value already comes back as str, never bytes.
            await redis.delete(*(f"{_TOKEN_PREFIX}{t}" for t in oldest))

    await redis.set(f"{_TOKEN_PREFIX}{token}", f"{user_id}:{video_asset_id}", ex=expires_in)
    return token


async def validate(redis: Redis, *, token: str, video_asset_id: uuid.UUID) -> uuid.UUID | None:
    """Returns the bound user_id if `token` is valid for this asset, else None."""
    raw = await redis.get(f"{_TOKEN_PREFIX}{token}")
    if raw is None:
        return None
    user_id_str, _, asset_id_str = raw.partition(":")
    if asset_id_str != str(video_asset_id):
        return None
    try:
        return uuid.UUID(user_id_str)
    except ValueError:  # pragma: no cover - the value is always our own
        return None


def rewrite_manifest(content: str, *, token: str) -> str:
    """Appends `?access_token=<token>` to every relative URI in an HLS
    manifest — plain lines (playlist/segment references) and the
    `#EXT-X-MAP:URI="..."` init-segment reference alike."""

    def _with_token(uri: str) -> str:
        sep = "&" if "?" in uri else "?"
        return f"{uri}{sep}access_token={token}"

    out: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-MAP:URI="):
            rewritten = _MAP_URI_RE.sub(
                lambda m: m.group(1) + _with_token(m.group(2)) + m.group(3), line
            )
            out.append(rewritten)
        elif stripped and not stripped.startswith("#"):
            out.append(_with_token(stripped))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


__all__ = ["mint", "rewrite_manifest", "validate"]
