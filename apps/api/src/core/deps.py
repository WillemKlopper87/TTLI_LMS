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
from src.services import tokens
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


# The two session dependencies below are deliberately written out twice
# rather than delegated through a shared inner generator. FastAPI delivers
# an endpoint's exception by *throwing it into the dependency generator at
# its yield* — and `async for s in inner(): yield s` does not forward that
# throw to `inner()`: the exception lands in the for-loop body, the loop
# unwinds, and `inner()` only ever sees GeneratorExit, so its
# except-AppError branch never runs. That exact miswiring silently
# disabled MFA lockout and refresh-reuse revocation when tried
# (tests/test_auth_flows.py caught it); keep these flat.


async def get_session(tenant: TenantDep) -> AsyncIterator[AsyncSession]:
    """A session already bound to the resolved tenant.

    Every exception — an AppError refusal included — rolls the transaction
    back. A service that flushes half an aggregate and then raises a
    business-rule refusal must not leave the half-written state behind;
    `tests/test_commerce.py`'s orphaned-draft-order regression is the
    precedent for exactly that failure. The one place a refusal must
    *keep* its writes (failed-attempt counters, the LOGIN_FAILED audit
    row that lockout depends on) is the auth router, which uses
    AuditedSessionDep below instead.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        await session.begin()
        await set_tenant(session, tenant.id)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


async def get_audited_session(tenant: TenantDep) -> AsyncIterator[AsyncSession]:
    """`get_session`, except an AppError commits what was flushed before it.

    An auth refusal is a business decision, not a transaction failure: the
    failed-attempt counter and LOGIN_FAILED audit row it just wrote are the
    record lockout depends on, and rolling them back with the refusal would
    silently disable lockout. Only the auth router should depend on this —
    anywhere else, commit-on-refusal turns a mid-service raise into
    persisted partial state.
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
AuditedSessionDep = Annotated[AsyncSession, Depends(get_audited_session)]


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


async def get_principal(
    request: Request, settings: SettingsDep, tenant: TenantDep, redis: RedisDep
) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise Unauthenticated("Authentication required.")

    try:
        claims = decode_access_token(header[7:].strip(), secret=settings.secret_key)
    except jwt.PyJWTError as exc:
        raise Unauthenticated("Authentication required.") from exc

    # Logout denylists the access token's jti for its remaining life
    # (routers/auth.py) — without this check the jti was minted and never
    # read, and "logout" left a bearer no mechanism could revoke. One
    # Redis EXISTS per authenticated request is the accepted cost; the
    # key expires with the token, so the set stays bounded.
    jti = claims.get("jti")
    if jti and await redis.exists(f"denylist:jti:{jti}"):
        raise Unauthenticated("Authentication required.")

    user_id = uuid.UUID(claims["sub"])
    # Suspending/locking/deleting an account (services/tenant_users.py
    # set_status) marks a cutoff instant instead of hunting down every jti
    # the user might be holding across tabs/devices. A bearer minted at or
    # before that instant stops working here immediately, not merely on its
    # own expiry — without this, suspension only took effect once every
    # outstanding access token aged out on its own. See
    # `tokens.is_access_token_revoked` for why the comparison is inclusive
    # (`<=`) and how reinstatement avoids the same-second ambiguity that
    # would otherwise create.
    revoked_at = await tokens.access_tokens_revoked_at(redis, user_id=user_id)
    if tokens.is_access_token_revoked(int(claims["iat"]), revoked_at):
        raise Unauthenticated("Authentication required.")

    token_tenant = uuid.UUID(claims["tid"])
    # The tenant is asserted twice — by hostname and by token claim. A single
    # source would make host spoofing a tenancy bypass.
    if token_tenant != tenant.id:
        raise Forbidden("You do not have access to this resource.")

    return Principal(
        user_id=user_id,
        tenant_id=token_tenant,
        permissions=frozenset(claims.get("perms", [])),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


__all__ = [
    "AuditedSessionDep",
    "CryptoDep",
    "Principal",
    "PrincipalDep",
    "RedisDep",
    "SessionDep",
    "SettingsDep",
    "TenantDep",
    "get_audited_session",
    "get_crypto",
    "get_principal",
    "get_redis_dep",
    "get_session",
    "get_tenant",
]
