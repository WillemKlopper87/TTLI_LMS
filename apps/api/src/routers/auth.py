from __future__ import annotations

from fastapi import APIRouter, Request

from src.core.deps import CryptoDep, PrincipalDep, SessionDep, SettingsDep, TenantDep
from src.core.errors import Unauthenticated
from src.core.security import issue_access_token
from src.models.audit import AuditAction
from src.models.user import User
from src.schemas.auth import LoginRequest, MeResponse, TokenResponse
from src.services import audit, identity

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for a token")
async def login(
    body: LoginRequest,
    request: Request,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> TokenResponse:
    user = await identity.authenticate(session, crypto, email=body.email, password=body.password)

    if user is None:
        await audit.record(
            session,
            tenant_id=tenant.id,
            action=AuditAction.LOGIN_FAILED,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            after={"email_domain": body.email.split("@", 1)[-1].lower()},
        )
        # Same message for unknown account, wrong password, locked and
        # suspended. The caller learns only that it did not work.
        raise Unauthenticated("Those credentials are not valid.")

    permissions = await identity.permissions_for(session, user.id)

    await audit.record(
        session,
        tenant_id=tenant.id,
        action=AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    token = issue_access_token(
        secret=settings.secret_key,
        user_id=user.id,
        tenant_id=tenant.id,
        permissions=permissions,
        minutes=settings.access_token_minutes,
    )
    return TokenResponse(access_token=token, expires_in=settings.access_token_minutes * 60)


@router.get("/me", response_model=MeResponse, summary="The current principal")
async def me(
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    tenant: TenantDep,
) -> MeResponse:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise Unauthenticated("Authentication required.")
    return MeResponse(
        user_id=str(principal.user_id),
        tenant_id=str(principal.tenant_id),
        tenant_slug=tenant.slug,
        email=crypto.decrypt(user.email_encrypted),
        permissions=sorted(principal.permissions),
    )


__all__ = ["router"]
