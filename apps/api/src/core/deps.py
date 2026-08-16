"""Request dependencies.

The ordering matters. Tenant resolution runs against a session with no tenant
set — it has to, because the tenant is not known yet, and `tenants` /
`tenant_domains` deliberately carry no RLS. Once resolved, every subsequent
session in the request is bound to that tenant.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.crypto import CryptoBox
from src.core.db import get_sessionmaker, set_tenant
from src.core.errors import AppError, Forbidden, TenantUnresolved, Unauthenticated
from src.core.redis import get_redis
from src.core.security import decode_access_token
from src.core.tenancy import TenantContext, get_or_resolve_tenant, hostname_from_request
from src.services.payments.base import PaymentProvider
from src.services.payments.payfast import PayfastProvider
from src.services.storage import StorageService, get_storage_adapter

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_redis_dep() -> Redis:
    return get_redis()


RedisDep = Annotated[Redis, Depends(get_redis_dep)]


async def get_tenant(request: Request, settings: SettingsDep, redis: RedisDep) -> TenantContext:
    cached = getattr(request.state, "tenant", None)
    if isinstance(cached, TenantContext):
        return cached

    hostname = hostname_from_request(request)
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        tenant = await get_or_resolve_tenant(session, redis, hostname)

    if tenant is None:
        raise TenantUnresolved(
            "No tenant is configured for this address.",
            {"hostname": hostname},
        )
    request.state.tenant = tenant
    return tenant


TenantDep = Annotated[TenantContext, Depends(get_tenant)]


async def get_session(tenant: TenantDep) -> AsyncIterator[AsyncSession]:
    """A session already bound to the resolved tenant.

    An AppError is a business decision the endpoint made deliberately — wrong
    password, invalid MFA code — not a failure of the transaction itself.
    Whatever it flushed before raising (a failed-attempt counter, a
    LOGIN_FAILED audit row) still commits; only genuinely unexpected
    exceptions roll back. A plain `async with session.begin():` cannot make
    this distinction — it rolls back on every exception alike, which would
    silently discard the very counters and audit rows lockout depends on.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        await session.begin()
        await set_tenant(session, tenant.id)
        try:
            yield session
        except AppError:
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_crypto(settings: SettingsDep) -> CryptoBox:
    return CryptoBox(settings.encryption_key_bytes(), settings.blind_index_key_bytes())


CryptoDep = Annotated[CryptoBox, Depends(get_crypto)]


def get_storage(settings: SettingsDep) -> StorageService:
    return get_storage_adapter(settings)


StorageDep = Annotated[StorageService, Depends(get_storage)]


def get_payment_provider(settings: SettingsDep) -> PaymentProvider:
    # A single, hardcoded provider today. When a second provider lands
    # (Merchant-of-Record, per the international-payments research —
    # see services/payments/payfast.py's module docstring), this becomes
    # a real selection (per-tenant currency/region, most likely), not a
    # config toggle bolted on here.
    return PayfastProvider(
        merchant_id=settings.payfast_merchant_id,
        merchant_key=settings.payfast_merchant_key,
        passphrase=settings.payfast_passphrase,
        sandbox=settings.payfast_sandbox,
    )


PaymentProviderDep = Annotated[PaymentProvider, Depends(get_payment_provider)]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    permissions: frozenset[str]

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise Forbidden("You do not have access to this resource.")


async def get_principal(request: Request, settings: SettingsDep, tenant: TenantDep) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise Unauthenticated("Authentication required.")

    try:
        claims = decode_access_token(header[7:].strip(), secret=settings.secret_key)
    except jwt.PyJWTError as exc:
        raise Unauthenticated("Authentication required.") from exc

    token_tenant = uuid.UUID(claims["tid"])
    # The tenant is asserted twice — by hostname and by token claim. A single
    # source would make host spoofing a tenancy bypass.
    if token_tenant != tenant.id:
        raise Forbidden("You do not have access to this resource.")

    return Principal(
        user_id=uuid.UUID(claims["sub"]),
        tenant_id=token_tenant,
        permissions=frozenset(claims.get("perms", [])),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


__all__ = [
    "CryptoDep",
    "Principal",
    "PrincipalDep",
    "RedisDep",
    "SessionDep",
    "SettingsDep",
    "TenantDep",
    "get_crypto",
    "get_principal",
    "get_redis_dep",
    "get_session",
    "get_tenant",
]
