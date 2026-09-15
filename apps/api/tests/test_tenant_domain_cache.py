"""Regression coverage for tenant-domain cache invalidation (F2).

Tenant resolution caches both hits and misses. Domain administration must
therefore evict the affected host on both create and delete; otherwise a new
domain can stay unresolved for the miss TTL and a removed domain can continue
routing to its old tenant for the positive-cache TTL.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.tenancy import invalidate_tenant_host_cache
from src.routers import tenant_branding as tenant_branding_router
from src.schemas.tenant_branding import AddDomainRequest


class _Principal:
    def __init__(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.user_id = uuid.uuid4()

    def require(self, permission: str) -> None:
        assert permission == tenant_branding_router.MANAGE


class _Redis:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, *keys: str) -> int:
        self.deleted.extend(keys)
        return len(keys)


def _domain(hostname: str = "customer.example.com") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        hostname=hostname,
        is_primary=False,
        verified_at=None,
        tls_status="pending",
    )


@pytest.mark.asyncio
async def test_cache_invalidation_normalises_the_hostname() -> None:
    redis = _Redis()

    await invalidate_tenant_host_cache(redis, " Customer.Example.COM. ")  # type: ignore[arg-type]

    assert redis.deleted == ["tenant:host:customer.example.com"]


@pytest.mark.asyncio
async def test_adding_a_domain_evicts_a_cached_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    principal = _Principal()
    redis = _Redis()
    domain = _domain()
    add = AsyncMock(return_value=domain)
    record = AsyncMock()
    monkeypatch.setattr(tenant_branding_router.branding, "add_domain", add)
    monkeypatch.setattr(tenant_branding_router.audit, "record", record)

    row = await tenant_branding_router.add_domain(
        body=AddDomainRequest(hostname="Customer.Example.COM"),
        principal=principal,  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        settings=SimpleNamespace(secret_key="test-secret"),  # type: ignore[arg-type]
        redis=redis,  # type: ignore[arg-type]
    )

    assert row.hostname == domain.hostname
    assert redis.deleted == ["tenant:host:customer.example.com"]
    add.assert_awaited_once()
    record.assert_awaited_once()


@pytest.mark.asyncio
async def test_removing_a_domain_evicts_a_cached_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    principal = _Principal()
    redis = _Redis()
    domain = _domain()
    remove = AsyncMock(return_value=domain)
    record = AsyncMock()
    monkeypatch.setattr(tenant_branding_router.branding, "remove_domain", remove)
    monkeypatch.setattr(tenant_branding_router.audit, "record", record)

    await tenant_branding_router.remove_domain(
        domain_id=domain.id,
        principal=principal,  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        tenant=SimpleNamespace(id=principal.tenant_id),  # type: ignore[arg-type]
        redis=redis,  # type: ignore[arg-type]
    )

    assert redis.deleted == ["tenant:host:customer.example.com"]
    remove.assert_awaited_once()
    record.assert_awaited_once()
