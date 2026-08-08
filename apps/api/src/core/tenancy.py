"""Tenant resolution.

The hostname is the first thing every request is judged on, so the lookup is
cached in Redis in production. For now it is a direct query; the cache lands in
sprint 2 alongside rate limiting, which needs Redis anyway.

`X-Tenant-Host` is set by the web tier's BFF. Falling back to the Host header
keeps direct API calls working in development.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.models.tenant import Tenant, TenantDomain


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


__all__ = ["TenantContext", "hostname_from_request", "resolve_tenant"]
