"""Single sign-on: the login flow, and the configuration behind it
(`docs/BACKLOG.md` P4, feature-matrix gap #46).

Two audiences again, and they need opposite gates:

* `GET /auth/sso/available` and the two flow endpoints are **anonymous
  by necessity** — they are how somebody without a session gets one.
* `GET/PUT/DELETE /tenant/sso` is `tenant:manage`, the same permission
  that governs branding and domains.

The anonymous half is the one to read carefully. `available` says only
whether SSO is on and what to label the button; it does not leak the
issuer, the client id, or the allowed domains, because an unauthenticated
caller asking "what does this company use" should not get an inventory
of a tenant's identity infrastructure.

The flow returns JSON with a URL rather than issuing HTTP redirects.
Every other authentication path in this API answers the BFF with JSON
and lets the browser tier navigate; a 302 here would be the one endpoint
that behaves differently, and it would bypass the BFF's own handling of
the session cookie it has to set at the end.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from src.core.deps import (
    AuditedSessionDep,
    CryptoDep,
    PrincipalDep,
    RedisDep,
    SessionDep,
    SettingsDep,
    TenantDep,
)
from src.core.errors import NotFound, Unauthenticated
from src.core.ids import uuid7
from src.core.security import issue_access_token
from src.models.audit import AuditAction
from src.models.sso import TenantIdpConfig
from src.schemas.auth import TokenResponse
from src.schemas.sso import (
    SsoAvailableResponse,
    SsoConfigRequest,
    SsoConfigResponse,
    SsoStartResponse,
)
from src.services import audit, identity, oidc, tokens
from src.services import tenant_users as people

router = APIRouter(tags=["auth"])

MANAGE = "tenant:manage"


class SsoCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=512)
    redirect_uri: str = Field(min_length=1, max_length=500)


@router.get(
    "/auth/sso/available",
    response_model=SsoAvailableResponse,
    summary="Whether this tenant has SSO, and what the button should say",
)
async def sso_available(session: SessionDep, tenant: TenantDep) -> SsoAvailableResponse:
    """Anonymous by necessity — the login page calls it before anyone has
    a session. Deliberately says nothing about the issuer or the allowed
    domains: "does this company use SSO" is a fair question for a login
    page, "what is their identity infrastructure" is not."""
    config = await oidc.get_config(session, tenant_id=tenant.id)
    return SsoAvailableResponse(
        available=config is not None,
        display_name=config.display_name if config else None,
    )


@router.post(
    "/auth/sso/start",
    response_model=SsoStartResponse,
    summary="Begin an SSO login — returns the URL to send the browser to",
)
async def sso_start(
    request: Request,
    session: SessionDep,
    tenant: TenantDep,
    redis: RedisDep,
    redirect_uri: Annotated[str, Field(max_length=500)] = "",
    next: Annotated[str | None, Field(max_length=200)] = None,
) -> SsoStartResponse:
    config = await oidc.get_config(session, tenant_id=tenant.id)
    if config is None:
        raise NotFound("This organisation does not use single sign-on.")

    target = redirect_uri or f"https://{tenant.hostname}/auth/sso/callback"
    discovery = await oidc.discover(config.issuer)
    url = await oidc.begin(
        redis,
        config=config,
        discovery=discovery,
        redirect_uri=target,
        next_path=next,
    )
    return SsoStartResponse(authorization_url=url)


@router.post(
    "/auth/sso/callback",
    response_model=TokenResponse,
    summary="Finish an SSO login — validates the id_token and issues a session",
)
async def sso_callback(
    body: SsoCallbackRequest,
    request: Request,
    session: AuditedSessionDep,
    tenant: TenantDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> TokenResponse:
    """Every check that matters lives in `services/oidc.py`; this reads
    as a sequence because that is what it is. The order is not
    cosmetic — the domain allowlist runs before any user lookup, so a
    hostile IdP never even causes an account to be searched for."""
    parked = await oidc.take_state(redis, body.state)
    if parked.get("tenant_id") != str(tenant.id):
        # State minted for another tenant's login, presented here.
        raise Unauthenticated("That sign-in attempt does not belong to this organisation.")

    config = await oidc.get_config(session, tenant_id=tenant.id)
    if config is None:
        raise NotFound("This organisation does not use single sign-on.")

    discovery = await oidc.discover(config.issuer)
    id_token = await oidc.exchange(
        config=config,
        crypto=crypto,
        discovery=discovery,
        code=body.code,
        verifier=str(parked["verifier"]),
        redirect_uri=str(parked.get("redirect_uri") or body.redirect_uri),
    )
    asserted = oidc.validate(
        id_token=id_token, config=config, discovery=discovery, nonce=str(parked["nonce"])
    )
    oidc.assert_domain_allowed(asserted.email, config)

    user = await identity.find_by_email(session, crypto, asserted.email)
    provisioned = user is None
    if user is None:
        # JIT provisioning. No password is ever set: this account exists
        # only through the IdP, and a password would be a second way in
        # that the tenant did not ask for and cannot revoke centrally.
        user = await identity.create_user(
            session,
            crypto,
            tenant_id=tenant.id,
            email=asserted.email,
            full_name=asserted.full_name,
        )

    if user.status == "suspended":
        # Suspension is this platform's decision and outranks the IdP's.
        raise Unauthenticated("That account is suspended.")

    granted: list[str] = []
    for role_code in oidc.roles_for(asserted, config):
        if await people.assign_role(session, tenant_id=tenant.id, user=user, role_code=role_code):
            granted.append(role_code)

    await audit.record(
        session,
        tenant_id=tenant.id,
        action=AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        after={
            "method": "sso",
            "issuer": config.issuer,
            "provisioned": provisioned,
            "roles_granted": granted,
        },
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    permissions = await identity.permissions_for(session, user.id)
    access_token = issue_access_token(
        secret=settings.secret_key,
        user_id=user.id,
        tenant_id=tenant.id,
        permissions=permissions,
        minutes=settings.access_token_minutes,
    )
    issued = await tokens.issue_family(
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        days=settings.refresh_token_days,
        device_fingerprint=request.headers.get("x-device-fingerprint"),
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=issued.raw,
        expires_in=settings.access_token_minutes * 60,
    )


def _config_response(config: TenantIdpConfig | None) -> SsoConfigResponse:
    """The client secret is never returned, not even masked back to the
    admin who set it — a write-only field is the whole point."""
    if config is None:
        return SsoConfigResponse(configured=False)
    return SsoConfigResponse(
        configured=True,
        protocol=config.protocol,
        display_name=config.display_name,
        issuer=config.issuer,
        client_id=config.client_id,
        allowed_email_domains=list(config.allowed_email_domains),
        group_role_map=dict(config.group_role_map or {}),
        default_role_code=config.default_role_code,
        enabled=config.enabled,
    )


@router.get(
    "/tenant/sso",
    response_model=SsoConfigResponse,
    summary="This tenant's identity-provider configuration",
)
async def get_sso_config(principal: PrincipalDep, session: SessionDep) -> SsoConfigResponse:
    principal.require(MANAGE)
    return _config_response(
        await oidc.get_config(session, tenant_id=principal.tenant_id, enabled_only=False)
    )


@router.put(
    "/tenant/sso",
    response_model=SsoConfigResponse,
    summary="Create or replace the identity-provider configuration",
)
async def put_sso_config(
    body: SsoConfigRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
    crypto: CryptoDep,
) -> SsoConfigResponse:
    """The issuer is contacted before the config is saved. A tenant that
    mistypes it should find out here, not at the moment a colleague
    cannot sign in."""
    principal.require(MANAGE)
    await oidc.discover(body.issuer)

    for role_code in {*body.group_role_map.values(), *([body.default_role_code] or [])}:
        if role_code:
            # The same no-escalation rule as manual role assignment: an
            # IdP group mapping is a role grant with extra steps, and it
            # would be a hole in that rule to skip the check here.
            await people.assert_can_grant(
                session, role_code=role_code, actor_permissions=principal.permissions
            )

    config = await oidc.get_config(session, tenant_id=principal.tenant_id, enabled_only=False)
    if config is None:
        config = TenantIdpConfig(id=uuid7(), tenant_id=principal.tenant_id)
        session.add(config)

    config.protocol = "oidc"
    config.display_name = body.display_name
    config.issuer = body.issuer
    config.client_id = body.client_id
    if body.client_secret:
        config.client_secret_encrypted = crypto.encrypt(body.client_secret)
    elif config.client_secret_encrypted is None:
        raise NotFound("A client secret is required the first time SSO is configured.")
    config.allowed_email_domains = [
        d.strip().lower().lstrip("@") for d in body.allowed_email_domains
    ]
    config.group_role_map = body.group_role_map
    config.default_role_code = body.default_role_code
    config.enabled = body.enabled
    await session.flush()

    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="tenant_idp_config",
        entity_id=config.id,
        # The secret is not in here either.
        after={
            "issuer": config.issuer,
            "enabled": config.enabled,
            "allowed_email_domains": config.allowed_email_domains,
            "group_role_map": config.group_role_map,
        },
    )
    return _config_response(config)


@router.delete(
    "/tenant/sso",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove the identity-provider configuration",
)
async def delete_sso_config(principal: PrincipalDep, session: AuditedSessionDep) -> None:
    principal.require(MANAGE)
    config = await oidc.get_config(session, tenant_id=principal.tenant_id, enabled_only=False)
    if config is None:
        raise NotFound("This organisation does not use single sign-on.")
    await session.delete(config)
    await session.flush()
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="tenant_idp_config",
        entity_id=config.id,
        after={"removed": True},
    )


__all__ = ["router"]
