"""Tenant resolution.

The hostname is the first thing every request is judged on, so the lookup is
cached in Redis (get_or_resolve_tenant) rather than hitting Postgres on
every request. A short TTL, not an invalidated-on-write cache: nothing in
Phase 1 lets an admin edit tenant_domains yet, so bounded staleness is a
simpler, sufficient trade for now — revisit once that exists.

`X-Tenant-Host` is set by the web tier's BFF. Falling back to the Host header
keeps direct API calls working in development.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.models.tenant import Tenant, TenantDomain

CACHE_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class TenantContext:
    id: uuid.UUID
    slug: str
    name: str
    hostname: str


def hostname_from_request(request: Request) -> str:
    raw = request.headers.get("x-tenant-host") or request.headers.get("host") or ""
    # Strip the port; "acme.example.co.za:8010" and the same host on 443 are one tenant.
    return raw.split(":", 1)[0].strip().lower()


async def resolve_tenant(session: AsyncSession, hostname: str) -> TenantContext | None:
    if not hostname:
        return None
    stmt = (
        select(Tenant.id, Tenant.slug, Tenant.name, TenantDomain.hostname)
        .join(TenantDomain, TenantDomain.tenant_id == Tenant.id)
        .where(TenantDomain.hostname == hostname)
        .where(Tenant.status == "active")
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return TenantContext(id=row[0], slug=row[1], name=row[2], hostname=row[3])


def _cache_key(hostname: str) -> str:
    return f"tenant:host:{hostname}"


async def get_or_resolve_tenant(
    session: AsyncSession, redis: Redis, hostname: str, *, ttl_seconds: int = CACHE_TTL_SECONDS
) -> TenantContext | None:
    if not hostname:
        return None

    cached = await redis.get(_cache_key(hostname))
    if cached is not None:
        payload = json.loads(cached)
        return TenantContext(**{**payload, "id": uuid.UUID(payload["id"])})

    tenant = await resolve_tenant(session, hostname)
    if tenant is not None:
        payload = json.dumps(asdict(tenant), default=str)
        await redis.set(_cache_key(hostname), payload, ex=ttl_seconds)
    return tenant


__all__ = [
    "CACHE_TTL_SECONDS",
    "TenantContext",
    "get_or_resolve_tenant",
    "hostname_from_request",
    "resolve_tenant",
]
