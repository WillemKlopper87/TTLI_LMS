"""Authentication.

Login is deliberately uniform: the same response and comparable timing whether
or not the account exists. The learner list is the customer's client list, and
confirming that a named executive has an account is itself a disclosure. The
same rule extends to the magic-link and MFA endpoints added in Sprint 2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from src.core.config import get_settings
from src.core.deps import (
    AuditedSessionDep,
    CryptoDep,
    PrincipalDep,
    RedisDep,
    SettingsDep,
    TenantDep,
)
from src.core.errors import TooManyAttempts, Unauthenticated
from src.core.net import client_ip
from src.core.security import (
    decode_access_token,
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
    LogoutRequest,
    MagicLinkConsumeRequest,
    MagicLinkRequest,
    MeResponse,
    MfaChallengeResponse,
    MfaEnrollConfirmRequest,
    MfaEnrollConfirmResponse,
    MfaEnrollResponse,
    MfaVerifyRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshRequest,
    TokenResponse,
)
from src.services import audit, events, identity, rate_limit, tokens
from src.services.email import send_email
from src.services.tokens import GuestAccessExpired, RefreshTokenReused

router = APIRouter(prefix="/auth", tags=["auth"])

MFA_PENDING_PURPOSE = "mfa_pending"
MFA_ENROLL_PURPOSE = "mfa_enroll"

# 03_API_SPEC.md §1.8: "Login and password reset | 10/min per IP, 5/min per
# account". Applied to login and the magic-link request — the two endpoints
# an enumeration or brute-force attempt would actually hit. mfa/verify has
# its own purpose-built 6-attempt/15-minute lockout instead (identity.py);
# stacking this on top of it would just be a second, looser limit. Numbers
# live in services/rate_limit.py's LOGIN_IP/LOGIN_ACCOUNT now (report M8) —
# this function stays local rather than becoming a plain Depends() because
# the account check needs `email` from the parsed request body, which
# FastAPI dependencies resolve before body parsing happens.


def _client_ip(request: Request) -> str | None:
    return client_ip(request, trust_x_forwarded_for=get_settings().trust_x_forwarded_for)


def _anonymous_id(request: Request) -> uuid.UUID | None:
    """No client-side anonymous-id cookie exists yet (that lands with the
    Phase 2 web tier) — a caller may pass one via header, otherwise
    events.record() mints a fresh one per call."""
    raw = request.headers.get("x-anonymous-id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def _enforce_login_rate_limit(redis: Redis, *, ip: str | None, email: str) -> None:
    if ip is not None:
        ip_ok = await rate_limit.hit(
            redis,
            key=f"ratelimit:{rate_limit.LOGIN_IP.key_prefix}:{ip}",
            limit=rate_limit.LOGIN_IP.limit,
            window_seconds=rate_limit.LOGIN_IP.window_seconds,
        )
        if not ip_ok:
            raise TooManyAttempts("Too many attempts. Try again shortly.")

    # Hashed, not the raw address — keyed the same way the blind index is,
    # so no plaintext email sits in Redis even for the 60-second window.
    account_key = hash_token(email.strip().lower()).hex()
    account_ok = await rate_limit.hit(
        redis,
        key=f"ratelimit:{rate_limit.LOGIN_ACCOUNT.key_prefix}:{account_key}",
        limit=rate_limit.LOGIN_ACCOUNT.limit,
        window_seconds=rate_limit.LOGIN_ACCOUNT.window_seconds,
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
    session: AuditedSessionDep,
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
    session: AuditedSessionDep,
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
        await events.record(
            session,
            tenant_id=tenant.id,
            event_name=events.EventName.LOGIN_FAILED,
            anonymous_id=_anonymous_id(request),
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
    await events.record(
        session,
        tenant_id=tenant.id,
        event_name=events.EventName.LOGIN_SUCCEEDED,
        anonymous_id=_anonymous_id(request),
        user_id=user.id,
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
    session: AuditedSessionDep,
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
        await events.record(
            session,
            tenant_id=tenant.id,
            event_name=events.EventName.MAGIC_LINK_REQUESTED,
            anonymous_id=_anonymous_id(request),
        )


@router.post(
    "/magic-link/consume", response_model=None, summary="Exchange a magic link for a token"
)
async def consume_magic_link(
    body: MagicLinkConsumeRequest,
    request: Request,
    session: AuditedSessionDep,
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
    session: AuditedSessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
    redis: RedisDep,
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
    if ok:
        # A challenge token is single-use per *successful* login (failed code
        # attempts may retry against the same challenge — the 6-attempt
        # lockout above bounds those). SET NX is the atomic claim: the second
        # successful use of the same token loses the race and is a replay.
        claimed = await redis.set(
            f"mfa:consumed:{hash_token(body.mfa_token).hex()}",
            "1",
            nx=True,
            ex=settings.mfa_pending_minutes * 60,
        )
        if not claimed:
            raise Unauthenticated("That MFA challenge is invalid or has expired.")
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
    session: AuditedSessionDep,
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
    except GuestAccessExpired as exc:
        raise Unauthenticated("Guest access has expired.") from exc
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
            await events.record(
                session,
                tenant_id=tenant.id,
                event_name=events.EventName.TOKEN_REUSE_DETECTED,
                anonymous_id=_anonymous_id(request),
                user_id=exc.user_id,
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


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the current session's refresh-token family",
)
async def logout(
    body: LogoutRequest,
    request: Request,
    session: AuditedSessionDep,
    tenant: TenantDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> None:
    """Ends this session only — revoke_all_for_user (all devices) is reserved
    for password-reset-confirm, where proof of mailbox justifies the wider
    blast radius. Always 204, whether or not the token was still live, so
    logout is idempotent and never leaks token state via status code."""
    # The access token dies with the session, not just the refresh family.
    # Its jti goes on the Redis denylist for exactly its remaining life —
    # before this, "logout" left a live bearer valid for up to
    # access_token_minutes, revocable by nothing. Best-effort decode: an
    # absent/expired/garbage Authorization header changes nothing about
    # logout's idempotent 204 contract.
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            claims = decode_access_token(auth_header[7:].strip(), secret=settings.secret_key)
            remaining = int(claims["exp"]) - int(datetime.now(UTC).timestamp())
            if claims.get("jti") and remaining > 0:
                await redis.set(f"denylist:jti:{claims['jti']}", "1", ex=remaining)
        except jwt.PyJWTError:
            pass

    user_id = await tokens.revoke_family_for_token(session, raw_token=body.refresh_token)
    if user_id is not None:
        await audit.record(
            session,
            tenant_id=tenant.id,
            action=AuditAction.LOGOUT,
            actor_user_id=user_id,
            entity_type="user",
            entity_id=user_id,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.post("/mfa/enroll", summary="Begin TOTP enrolment for the current user")
async def mfa_enroll(
    principal: PrincipalDep, session: AuditedSessionDep, crypto: CryptoDep, settings: SettingsDep
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
    session: AuditedSessionDep,
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


@router.post(
    "/password-reset",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Request a password-reset link",
)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    session: AuditedSessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
    redis: RedisDep,
) -> None:
    """Always 204, whether or not the address exists — same enumeration rule
    as the magic-link request (03_API_SPEC.md §2.8)."""
    await _enforce_login_rate_limit(redis, ip=_client_ip(request), email=body.email)
    raw = await identity.create_password_reset(
        session,
        crypto,
        tenant_id=tenant.id,
        email=body.email,
        minutes=settings.password_reset_minutes,
    )
    if raw is not None:
        link = f"https://{tenant.hostname}/auth/password-reset?token={raw}"
        await send_email(
            settings,
            to=body.email,
            subject=f"Reset your {tenant.name} password",
            body=(
                f"Use this link to choose a new password "
                f"(valid {settings.password_reset_minutes} minutes):\n\n{link}\n\n"
                f"If you did not request this, ignore this email — "
                f"your password has not changed."
            ),
        )
        await events.record(
            session,
            tenant_id=tenant.id,
            event_name=events.EventName.PASSWORD_RESET_REQUESTED,
            anonymous_id=_anonymous_id(request),
        )


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Set a new password with a reset token",
)
async def confirm_password_reset(
    body: PasswordResetConfirmRequest,
    request: Request,
    session: AuditedSessionDep,
    tenant: TenantDep,
) -> None:
    user = await identity.consume_password_reset(
        session, raw_token=body.token, new_password=body.new_password
    )
    if user is None:
        raise Unauthenticated("That link is invalid or has expired.")

    # Proof of the mailbox is not proof that existing sessions are the same
    # person. Every refresh-token family dies; the next login starts fresh.
    await tokens.revoke_all_for_user(session, user_id=user.id)

    await audit.record(
        session,
        tenant_id=tenant.id,
        action=AuditAction.PASSWORD_CHANGED,
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.get("/me", response_model=MeResponse, summary="The current principal")
async def me(
    principal: PrincipalDep,
    session: AuditedSessionDep,
    crypto: CryptoDep,
    tenant: TenantDep,
) -> MeResponse:
    user = await session.get(User, principal.user_id)
    if user is None:
        raise Unauthenticated("Authentication required.")
    who = identity.display_identity(user, crypto)
    return MeResponse(
        user_id=str(principal.user_id),
        tenant_id=str(principal.tenant_id),
        tenant_slug=tenant.slug,
        email=crypto.decrypt(user.email_encrypted),
        permissions=sorted(principal.permissions),
        full_name=who.full_name,
        first_name=who.first_name,
        initials=who.initials,
        is_guest=user.is_guest,
        guest_expires_at=user.guest_expires_at,
        guest_days_left=identity.guest_days_left(user),
    )


__all__ = ["router"]
