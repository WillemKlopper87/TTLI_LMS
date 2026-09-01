"""Redis-backed rate limiting: fixed-window counters.

INCR is atomic; EXPIRE NX on every hit sets the window only when the key has
no TTL yet. That heals the crash window between a first INCR and its EXPIRE —
whichever hit comes next re-arms the expiry instead of the key living forever
at its counted value. Fixed windows allow up to 2x the limit across a window
boundary; accepted, the spec's limits have that headroom.

Route classes (report M8): every per-IP limit used to be a one-off —
its own module-level constants, its own `_client_ip` wrapper copy-pasted
across four routers, its own inline "if ip is None: return" / raise. Six
near-identical private functions for what is really three distinct
risk profiles (an abuse-prone write, a browsable read, a login attempt)
made every new endpoint's author choose a number from nothing, and made
"what's our leads-capture budget vs. our public-catalogue budget"
unanswerable without reading six files. A named class here is the
answer, documented once, reused everywhere the same risk profile
applies — a future endpoint picks an existing class rather than
inventing a new magic number, and the numbers already in production
behaviour (login, leads, guest access, verification, engagement events)
are carried over unchanged, not silently retuned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from starlette.requests import Request

from src.core.config import get_settings
from src.core.deps import RedisDep
from src.core.errors import TooManyAttempts
from src.core.net import client_ip

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


async def hit(redis: Redis, *, key: str, limit: int, window_seconds: int) -> bool:
    """Record one hit against `key`. Returns True while still within `limit`."""
    count = int(await redis.incr(key))
    await redis.expire(key, window_seconds, nx=True)
    return count <= limit


@dataclass(frozen=True, slots=True)
class RouteClass:
    """A named per-IP budget. `key_prefix` namespaces the Redis key so two
    classes never collide even if their numbers happen to match."""

    key_prefix: str
    limit: int
    window_seconds: int


# Each constant keeps its call site's exact pre-existing Redis key prefix —
# migrating to a shared class must not reset anyone's live counter or quietly
# merge two previously-independent budgets into one shared bucket. What's
# shared is the *policy* (the number, the reasoning, one place to find both),
# not necessarily the counter itself.

# Login attempts — auth.py's own two-tier IP + account budget (03 §1.8).
LOGIN_IP = RouteClass("auth:ip", limit=10, window_seconds=60)
LOGIN_ACCOUNT = RouteClass("auth:account", limit=5, window_seconds=60)

# Unauthenticated writes that capture contact/PII or grant access to paid
# content — the tightest budgets, each still its own independent counter.
LEADS = RouteClass("leads", limit=5, window_seconds=3600)
GUEST_ACCESS = RouteClass("guest-access", limit=5, window_seconds=3600)

# A credential's public verification page — low-volume by nature (someone
# checking one certificate).
PUBLIC_VERIFY = RouteClass("verify", limit=20, window_seconds=3600)

# View/engagement events (article read, podcast play) — high-frequency but
# low-value-per-hit. Same numbers, independent counters: a burst of article
# reads must not spend a visitor's podcast-play budget or vice versa.
ARTICLE_EVENTS = RouteClass("article-events", limit=60, window_seconds=60)
PODCAST_EVENTS = RouteClass("podcast-events", limit=60, window_seconds=60)
# Fires once per client-side navigation across the whole public site
# (checklist item 20 follow-up, 01_PRD.md §5.11) — higher than the two
# above since a visitor browsing normally crosses far more marketing
# pages per minute than they read articles or start podcast plays.
PAGE_EVENTS = RouteClass("page-events", limit=120, window_seconds=60)

# Browsing the public catalogue/content surface (list + detail: courses,
# curricula, lesson previews, learning paths, podcasts, articles,
# recommendations, workshops) — no endpoint in this class carried any limit
# before this pass, the exact gap report M8 names. One shared counter across
# all of it, deliberately: bounding *total* scrape volume from one IP is the
# point, not bounding each content type separately (which would let a
# scraper pull the whole catalogue at N times the intended rate just by
# spreading requests across courses/podcasts/articles/paths/workshops).
# Generous on purpose: a real visitor or a search-engine crawler browsing
# normally never comes close.
PUBLIC_READ = RouteClass("public-read", limit=300, window_seconds=60)

DEFAULT_MESSAGE = "Too many attempts. Try again later."


async def enforce_ip_limit(
    redis: Redis,
    request: Request,
    route_class: RouteClass,
    *,
    trust_x_forwarded_for: bool,
    message: str = DEFAULT_MESSAGE,
) -> None:
    """No-ops when the client address can't be resolved at all — same
    fail-open stance every one-off check already took, since refusing a
    request over a missing IP (proxy misconfiguration, not the caller's
    fault) is a worse failure mode than an unlimited request."""
    ip = client_ip(request, trust_x_forwarded_for=trust_x_forwarded_for)
    if ip is None:
        return
    ok = await hit(
        redis,
        key=f"ratelimit:{route_class.key_prefix}:ip:{ip}",
        limit=route_class.limit,
        window_seconds=route_class.window_seconds,
    )
    if not ok:
        raise TooManyAttempts(message)


def rate_limited(
    route_class: RouteClass, *, message: str = DEFAULT_MESSAGE
) -> Callable[[Request, Redis], Coroutine[None, None, None]]:
    """A FastAPI dependency factory: `Depends(rate_limited(PUBLIC_READ))`.
    Reads `TRUST_X_FORWARDED_FOR` itself via `get_settings()` rather than
    taking it as a parameter, so route signatures stay a one-liner — every
    call site already gets that value from the same source (`core/config.py`),
    never per-request.
    """

    async def _dependency(request: Request, redis: RedisDep) -> None:
        await enforce_ip_limit(
            redis,
            request,
            route_class,
            trust_x_forwarded_for=get_settings().trust_x_forwarded_for,
            message=message,
        )

    return _dependency


__all__ = [
    "ARTICLE_EVENTS",
    "DEFAULT_MESSAGE",
    "GUEST_ACCESS",
    "LEADS",
    "LOGIN_ACCOUNT",
    "LOGIN_IP",
    "PAGE_EVENTS",
    "PODCAST_EVENTS",
    "PUBLIC_READ",
    "PUBLIC_VERIFY",
    "RouteClass",
    "enforce_ip_limit",
    "hit",
    "rate_limited",
]
