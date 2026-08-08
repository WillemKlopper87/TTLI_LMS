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
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.core.crypto import CryptoBox
from src.core.db import get_sessionmaker, set_tenant
from src.core.errors import Forbidden, TenantUnresolved, Unauthenticated
from src.core.security import decode_access_token
from src.core.tenancy import TenantContext, hostname_from_request, resolve_tenant

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_tenant(request: Request, settings: SettingsDep) -> TenantContext:
    cached = getattr(request.state, "tenant", None)
    if isinstance(cached, TenantContext):
        return cached

    hostname = hostname_from_request(request)
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        tenant = await resolve_tenant(session, hostname)

    if tenant is None:
        raise TenantUnresolved(
            "No tenant is configured for this address.",
            {"hostname": hostname},
        )
    request.state.tenant = tenant
    return tenant


TenantDep = Annotated[TenantContext, Depends(get_tenant)]


async def get_session(tenant: TenantDep) -> AsyncIterator[AsyncSession]:
    """A session already bound to the resolved tenant."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        await set_tenant(session, tenant.id)
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_crypto(settings: SettingsDep) -> CryptoBox:
    return CryptoBox(settings.encryption_key_bytes(), settings.blind_index_key_bytes())


CryptoDep = Annotated[CryptoBox, Depends(get_crypto)]


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
    "SessionDep",
    "SettingsDep",
    "TenantDep",
    "get_crypto",
    "get_principal",
    "get_session",
    "get_tenant",
]
