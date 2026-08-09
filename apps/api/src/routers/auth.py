"""Authentication.

Login is deliberately uniform: the same response and comparable timing whether
or not the account exists. The learner list is the customer's client list, and
confirming that a named executive has an account is itself a disclosure. The
same rule extends to the magic-link and MFA endpoints added in Sprint 2.
"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from src.core.deps import CryptoDep, PrincipalDep, RedisDep, SessionDep, SettingsDep, TenantDep
from src.core.errors import TooManyAttempts, Unauthenticated
from src.core.security import (
    decode_purpose_token,
    hash_token,
    issue_access_token,
    issue_purpose_token,
    new_totp_secret,
    totp_provisioning_uri,
    verify_totp,
)
from src.models.audit import AuditAction
from src.models.user import User
from src.schemas.auth import (
    LoginRequest,
    MagicLinkConsumeRequest,
    MagicLinkRequest,
    MeResponse,
    MfaChallengeResponse,
    MfaEnrollConfirmRequest,
    MfaEnrollConfirmResponse,
    MfaEnrollResponse,
    MfaVerifyRequest,
    RefreshRequest,
    TokenResponse,
)
from src.services import audit, identity, rate_limit, tokens
from src.services.email import send_email
from src.services.tokens import RefreshTokenReused

router = APIRouter(prefix="/auth", tags=["auth"])

MFA_PENDING_PURPOSE = "mfa_pending"
MFA_ENROLL_PURPOSE = "mfa_enroll"

# 03_API_SPEC.md §1.8: "Login and password reset | 10/min per IP, 5/min per
# account". Applied to login and the magic-link request — the two endpoints
# an enumeration or brute-force attempt would actually hit. mfa/verify has
# its own purpose-built 6-attempt/15-minute lockout instead (identity.py);
# stacking this on top of it would just be a second, looser limit.
LOGIN_RATE_LIMIT_PER_IP = 10
LOGIN_RATE_LIMIT_PER_ACCOUNT = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _enforce_login_rate_limit(redis: Redis, *, ip: str | None, email: str) -> None:
    if ip is not None:
        ip_ok = await rate_limit.hit(
            redis,
            key=f"ratelimit:auth:ip:{ip}",
            limit=LOGIN_RATE_LIMIT_PER_IP,
            window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )
        if not ip_ok:
            raise TooManyAttempts("Too many attempts. Try again shortly.")

    # Hashed, not the raw address — keyed the same way the blind index is,
    # so no plaintext email sits in Redis even for the 60-second window.
    account_key = hash_token(email.strip().lower()).hex()
    account_ok = await rate_limit.hit(
        redis,
        key=f"ratelimit:auth:account:{account_key}",
        limit=LOGIN_RATE_LIMIT_PER_ACCOUNT,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not account_ok:
        raise TooManyAttempts("Too many attempts. Try again shortly.")


def _mfa_required(user: User) -> bool:
    return user.mfa_secret_encrypted is not None and user.mfa_enforced_at is not None


def _mfa_challenge(*, settings: SettingsDep, user: User, tenant: TenantDep) -> JSONResponse:
    mfa_token = issue_purpose_token(
        secret=settings.secret_key,
        purpose=MFA_PENDING_PURPOSE,
        claims={"sub": str(user.id), "tid": str(tenant.id)},
        minutes=settings.mfa_pending_minutes,
    )
    body = MfaChallengeResponse(mfa_token=mfa_token)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=jsonable_encoder(body))


async def _issue_session(
    session: SessionDep,
    *,
    tenant: TenantDep,
    user: User,
    settings: SettingsDep,
    device_fingerprint: str | None,
) -> TokenResponse:
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
        device_fingerprint=device_fingerprint,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=issued.raw,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post(
    "/login",
    response_model=None,
    summary="Exchange credentials for a token, or an MFA challenge",
)
async def login(
    body: LoginRequest,
    request: Request,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
    redis: RedisDep,
) -> TokenResponse | JSONResponse:
    await _enforce_login_rate_limit(redis, ip=_client_ip(request), email=body.email)
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

    if _mfa_required(user):
        return _mfa_challenge(settings=settings, user=user, tenant=tenant)

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
    return await _issue_session(
        session,
        tenant=tenant,
        user=user,
        settings=settings,
        device_fingerprint=request.headers.get("x-device-fingerprint"),
    )


@router.post(
    "/magic-link",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Request a magic sign-in link",
)
async def request_magic_link(
    body: MagicLinkRequest,
    request: Request,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
    redis: RedisDep,
) -> None:
    """Always 204, whether or not the address exists — enumeration is the
    entire attack here (03_API_SPEC.md §2.2)."""
    await _enforce_login_rate_limit(redis, ip=_client_ip(request), email=body.email)
    raw = await identity.create_magic_link(
        session, crypto, tenant_id=tenant.id, email=body.email, minutes=settings.magic_link_minutes
    )
    if raw is not None:
        link = f"https://{tenant.hostname}/auth/magic-link?token={raw}"
        await send_email(
            settings,
            to=body.email,
            subject=f"Your {tenant.name} sign-in link",
            body=(
                f"Use this link to sign in (valid {settings.magic_link_minutes} minutes):\n\n"
                f"{link}\n\nIf you did not request this, ignore this email."
            ),
        )


@router.post(
    "/magic-link/consume", response_model=None, summary="Exchange a magic link for a token"
)
async def consume_magic_link(
    body: MagicLinkConsumeRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> TokenResponse | JSONResponse:
    user = await identity.consume_magic_link(session, raw_token=body.token)
    if user is None:
        raise Unauthenticated("That link is invalid or has expired.")

    if _mfa_required(user):
        return _mfa_challenge(settings=settings, user=user, tenant=tenant)

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
    return await _issue_session(
        session,
        tenant=tenant,
        user=user,
        settings=settings,
        device_fingerprint=request.headers.get("x-device-fingerprint"),
    )


@router.post("/mfa/verify", summary="Complete a login that required MFA")
async def mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> TokenResponse:
    try:
        claims = decode_purpose_token(
            body.mfa_token, secret=settings.secret_key, purpose=MFA_PENDING_PURPOSE
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated("That MFA challenge is invalid or has expired.") from exc

    if claims["tid"] != str(tenant.id):
        raise Unauthenticated("That MFA challenge is invalid or has expired.")

    user = await session.get(User, claims["sub"])
    if user is None:
        raise Unauthenticated("That MFA challenge is invalid or has expired.")

    if identity.is_mfa_locked(user):
        raise TooManyAttempts("Too many failed attempts. Try again in 15 minutes.")

    ok = await identity.verify_mfa_code(session, crypto, user=user, code=body.code)
    if not ok:
        if identity.is_mfa_locked(user):
            await audit.record(
                session,
                tenant_id=tenant.id,
                action=AuditAction.MFA_LOCKED,
                actor_user_id=user.id,
                entity_type="user",
                entity_id=user.id,
                ip=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
            raise TooManyAttempts("Too many failed attempts. Try again in 15 minutes.")
        raise Unauthenticated("That code is not valid.")

    await audit.record(
        session,
        tenant_id=tenant.id,
        action=AuditAction.MFA_VERIFIED,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
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
    return await _issue_session(
        session,
        tenant=tenant,
        user=user,
        settings=settings,
        device_fingerprint=request.headers.get("x-device-fingerprint"),
    )


@router.post("/refresh", summary="Rotate a refresh token")
async def refresh(
    body: RefreshRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> TokenResponse:
    try:
        user_id, issued = await tokens.rotate(
            session,
            tenant_id=tenant.id,
            raw_token=body.refresh_token,
            days=settings.refresh_token_days,
            device_fingerprint=request.headers.get("x-device-fingerprint"),
        )
    except RefreshTokenReused as exc:
        if exc.user_id is not None:
            await audit.record(
                session,
                tenant_id=tenant.id,
                action=AuditAction.TOKEN_REUSE_DETECTED,
                actor_user_id=exc.user_id,
                entity_type="user",
                entity_id=exc.user_id,
                ip=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
        raise Unauthenticated("That refresh token is no longer valid.") from exc

    user = await session.get(User, user_id)
    if user is None:
        raise Unauthenticated("That refresh token is no longer valid.")

    await audit.record(
        session,
        tenant_id=tenant.id,
        action=AuditAction.TOKEN_REFRESHED,
        actor_user_id=user_id,
        entity_type="user",
        entity_id=user_id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    permissions = await identity.permissions_for(session, user_id)
    access_token = issue_access_token(
        secret=settings.secret_key,
        user_id=user_id,
        tenant_id=tenant.id,
        permissions=permissions,
        minutes=settings.access_token_minutes,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=issued.raw,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/mfa/enroll", summary="Begin TOTP enrolment for the current user")
async def mfa_enroll(
    principal: PrincipalDep, session: SessionDep, crypto: CryptoDep, settings: SettingsDep
) -> MfaEnrollResponse:
    """Not yet in 03_API_SPEC.md §2 — that section documents verification, not
    the enrolment step it presupposes. Added here as the minimum plumbing
    needed for §1.3's "TOTP, mandatory for Finance, Administrator..." to be
    actionable at all.
    """
    user = await session.get(User, principal.user_id)
    if user is None:
        raise Unauthenticated("Authentication required.")

    secret = new_totp_secret()
    email = crypto.decrypt(user.email_encrypted)
    otpauth_uri = totp_provisioning_uri(
        secret=secret, account_email=email, issuer=settings.mfa_issuer_name
    )
    enrollment_token = issue_purpose_token(
        secret=settings.secret_key,
        purpose=MFA_ENROLL_PURPOSE,
        claims={"sub": str(principal.user_id), "tid": str(principal.tenant_id), "secret": secret},
        minutes=settings.mfa_enroll_minutes,
    )
    return MfaEnrollResponse(
        secret=secret, otpauth_uri=otpauth_uri, enrollment_token=enrollment_token
    )


@router.post("/mfa/enroll/confirm", summary="Confirm TOTP enrolment with a live code")
async def mfa_enroll_confirm(
    body: MfaEnrollConfirmRequest,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> MfaEnrollConfirmResponse:
    try:
        claims = decode_purpose_token(
            body.enrollment_token, secret=settings.secret_key, purpose=MFA_ENROLL_PURPOSE
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated("That enrolment attempt is invalid or has expired.") from exc

    if claims["sub"] != str(principal.user_id) or claims["tid"] != str(principal.tenant_id):
        raise Unauthenticated("That enrolment attempt is invalid or has expired.")

    if not verify_totp(secret=claims["secret"], code=body.code):
        raise Unauthenticated("That code is not valid.")

    user = await session.get(User, principal.user_id)
    if user is None:
        raise Unauthenticated("Authentication required.")

    codes = await identity.enroll_mfa(session, crypto, user=user, secret=claims["secret"])
    await audit.record(
        session,
        tenant_id=tenant.id,
        action=AuditAction.MFA_ENROLLED,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MfaEnrollConfirmResponse(recovery_codes=codes)


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
