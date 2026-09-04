"""Refresh-token issuance and rotation.

Rotation reuses detection as the theft signal: reuse of an already-consumed
token revokes every row sharing its family_id — including whichever token is
currently active — forcing a fresh login. See 04_SECURITY_AND_COMPLIANCE.md
§1.2 and 03_API_SPEC.md §2.5.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.core.security import hash_token, new_token
from src.models.auth import RefreshToken


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    raw: str
    family_id: uuid.UUID
    expires_at: datetime


class RefreshTokenReused(Exception):
    """Raised when a consumed or revoked token is presented again.

    `user_id` is set only when the reused token belonged to a known family —
    the caller uses it to attribute the audit event this raises for.
    """

    def __init__(self, message: str, *, user_id: uuid.UUID | None = None) -> None:
        super().__init__(message)
        self.user_id = user_id


class GuestAccessExpired(Exception):
    """Raised when a guest's refresh token is presented after guest_expires_at.

    Deliberately not a RefreshTokenReused — an expired guest is not a theft
    signal, and treating it as one would revoke the family and fire an
    incorrect TOKEN_REUSE_DETECTED audit event for ordinary expiry.
    """


async def issue_family(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    days: int,
    device_fingerprint: str | None = None,
) -> IssuedRefreshToken:
    """Start a new rotation chain — called once per login."""
    return await _issue(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        family_id=uuid7(),
        days=days,
        device_fingerprint=device_fingerprint,
    )


async def _issue(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    days: int,
    device_fingerprint: str | None,
) -> IssuedRefreshToken:
    raw = new_token()
    expires_at = datetime.now(UTC) + timedelta(days=days)
    session.add(
        RefreshToken(
            tenant_id=tenant_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_token(raw),
            device_fingerprint=device_fingerprint,
            expires_at=expires_at,
        )
    )
    await session.flush()
    return IssuedRefreshToken(raw=raw, family_id=family_id, expires_at=expires_at)


async def rotate(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    raw_token: str,
    days: int,
    device_fingerprint: str | None = None,
) -> tuple[uuid.UUID, IssuedRefreshToken]:
    """Consume `raw_token` and issue its successor.

    Returns (user_id, new token). Raises RefreshTokenReused — which the caller
    must treat as a hard failure, not a retryable one — on replay of a
    consumed or already-revoked token. RLS scopes the lookup to `tenant_id`
    already; a token from another tenant simply is not found.

    The consuming UPDATE is a single statement guarded by `consumed_at IS
    NULL`, so two concurrent callers presenting the same raw token race at the
    database, not in application code — only one can ever win the row.
    """
    token_hash = hash_token(raw_token)
    now = datetime.now(UTC)

    # Bounds a guest's *whole* session lifetime, not just login: without this,
    # a refresh token issued before guest_expires_at could keep rotating past
    # it (REQ-LEAD-05, "time-limited"). Checked separately from the consuming
    # UPDATE below and raised as its own exception — folding it into that
    # UPDATE's WHERE clause would make an expired guest's refresh attempt
    # fall into the reuse/theft diagnosis path and wrongly revoke the family
    # plus fire a TOKEN_REUSE_DETECTED audit event for what is just expiry.
    guest_stmt = text(
        "SELECT u.is_guest, u.guest_expires_at FROM refresh_tokens rt "
        "JOIN users u ON u.id = rt.user_id WHERE rt.token_hash = :h"
    )
    guest_row = (await session.execute(guest_stmt, {"h": token_hash})).first()
    if guest_row is not None:
        is_guest, guest_expires_at = guest_row
        if is_guest and guest_expires_at is not None and guest_expires_at <= now:
            raise GuestAccessExpired("Guest access has expired.")

    # Device binding (04 §1.2): when the row recorded a fingerprint and the
    # caller presents a different one, the UPDATE matches nothing and the
    # rotation is refused. A caller presenting none is tolerated — the header
    # is optional — which keeps this a tripwire for naive theft, not a
    # guarantee against an attacker who also copied the fingerprint.
    consume_stmt = text(
        "UPDATE refresh_tokens SET consumed_at = :now "
        "WHERE token_hash = :h AND consumed_at IS NULL AND revoked_at IS NULL "
        "AND expires_at > :now "
        "AND (device_fingerprint IS NULL OR CAST(:fp AS text) IS NULL "
        "OR device_fingerprint = CAST(:fp AS text)) "
        "RETURNING user_id, family_id, device_fingerprint"
    )
    won = (
        await session.execute(consume_stmt, {"now": now, "h": token_hash, "fp": device_fingerprint})
    ).first()

    if won is not None:
        user_id, family_id, existing_fp = won
        issued = await _issue(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            family_id=family_id,
            days=days,
            device_fingerprint=device_fingerprint or existing_fp,
        )
        return user_id, issued

    # Lost the race above, or the token was never eligible — either way,
    # this is the reuse/theft path. Look up why, then fail hard.
    lookup_stmt = select(
        RefreshToken.user_id,
        RefreshToken.family_id,
        RefreshToken.consumed_at,
        RefreshToken.revoked_at,
        RefreshToken.expires_at,
    ).where(RefreshToken.token_hash == token_hash)
    existing = (await session.execute(lookup_stmt)).first()

    if existing is None:
        raise RefreshTokenReused("no such token")
    reused_user_id, family_id, consumed_at, revoked_at, expires_at = existing
    if revoked_at is None and consumed_at is not None:
        await _revoke_family(session, family_id=family_id)
        raise RefreshTokenReused("token already consumed", user_id=reused_user_id)
    if revoked_at is None and consumed_at is None and expires_at > now:
        # Live token, lost only on the fingerprint clause: a device-binding
        # mismatch. Refused but not consumed and the family stays alive —
        # revoking here would let anyone holding a stolen token DoS the
        # legitimate session just by presenting a wrong fingerprint.
        raise RefreshTokenReused("device fingerprint mismatch", user_id=reused_user_id)
    raise RefreshTokenReused("token family already revoked or expired", user_id=reused_user_id)


async def _revoke_family(session: AsyncSession, *, family_id: uuid.UUID) -> None:
    stmt = select(RefreshToken).where(RefreshToken.family_id == family_id)
    rows = (await session.execute(stmt)).scalars().all()
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    await session.flush()


async def revoke_family_for_token(session: AsyncSession, *, raw_token: str) -> uuid.UUID | None:
    """Revoke only the family `raw_token` belongs to — used by logout.

    Narrower than revoke_all_for_user: a logout should end this session, not
    every device. Returns the owning user_id, or None (a no-op, not an error)
    if the token is unknown or already dead, so logout stays idempotent.
    """
    token_hash = hash_token(raw_token)
    stmt = select(RefreshToken.user_id, RefreshToken.family_id).where(
        RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    user_id: uuid.UUID = row.user_id
    family_id: uuid.UUID = row.family_id
    await _revoke_family(session, family_id=family_id)
    return user_id


async def revoke_all_for_user(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Revoke every live refresh token the user holds, across all families.

    Called on password reset: proof-of-mailbox does not prove the old
    sessions are the same person, so they all die (03_API_SPEC.md §2.8).
    """
    stmt = text(
        "UPDATE refresh_tokens SET revoked_at = :now "
        "WHERE user_id = :u AND revoked_at IS NULL RETURNING 1"
    )
    revoked = (await session.execute(stmt, {"now": datetime.now(UTC), "u": user_id})).all()
    await session.flush()
    return len(revoked)


def _access_denylist_key(user_id: uuid.UUID) -> str:
    return f"denylist:user:{user_id}"


async def revoke_access_tokens_for_user(
    redis: Redis, *, user_id: uuid.UUID, ttl_seconds: int
) -> None:
    """Invalidate every access token already issued to this user.

    Unlike logout's single-jti denylist (`routers/auth.py`), the caller here
    — an administrator suspending someone else's account — never holds the
    jti to blacklist individually, and the user may be holding several
    (multiple tabs/devices). This records a cutoff instant instead: `core/
    deps.get_principal` refuses any bearer whose `iat` is not after it (see
    `is_access_token_revoked` for exactly what "after" means at whole-second
    resolution), which catches every access token outstanding at the moment
    of the call regardless of how many there are.

    `ttl_seconds` should be at least the access-token lifetime — once every
    token that could have existed before the cutoff has expired on its own,
    the marker is safe to expire too rather than growing this key forever.
    """
    key = _access_denylist_key(user_id)
    now = int(datetime.now(UTC).timestamp())
    await redis.set(key, str(now), ex=ttl_seconds)


async def clear_access_token_revocation(redis: Redis, *, user_id: uuid.UUID) -> None:
    """Undo `revoke_access_tokens_for_user` — called when a suspension is
    lifted (`services/tenant_users.py::set_status` back to active).

    Without this, the marker set by `revoke_access_tokens_for_user` simply
    outlives the suspension (it's on its own `ttl_seconds` clock, not tied to
    the status flip back to active), and a fresh login minted moments after
    reinstatement can land in the very same whole second the old marker was
    written in. `is_access_token_revoked` cannot tell that apart from the
    original "suspend right after login" case it exists to catch — the two
    look identical at one-second resolution — so the marker has to be
    deleted outright rather than out-raced by a timestamp comparison.
    """
    await redis.delete(_access_denylist_key(user_id))


async def access_tokens_revoked_at(redis: Redis, *, user_id: uuid.UUID) -> int | None:
    """The cutoff instant set by `revoke_access_tokens_for_user`, or None if
    the user has no active denylist mark (never suspended, reinstated since
    — see `clear_access_token_revocation` — or the mark has since expired
    because every pre-cutoff token is long dead anyway)."""
    raw = await redis.get(_access_denylist_key(user_id))
    return int(raw) if raw is not None else None


def is_access_token_revoked(iat: int, revoked_at: int | None) -> bool:
    """Whether an access token minted at `iat` (whole seconds, RFC 7519) is
    caught by `revoked_at` (whole seconds).

    `<=`, not `<`: `iat` has only whole-second resolution, so a suspend that
    lands in the very same second as the login it's meant to kill must not
    be able to lose that race just because both rounded to the same integer
    — the whole point of `revoke_access_tokens_for_user` is that the
    suspension takes effect immediately, not "immediately, unless the
    server was already warm enough to finish both calls inside one second."
    This does mean a token minted in the same second as the cutoff is always
    treated as revoked, with no way to tell "before" from "after" apart at
    this resolution — which is why reinstatement clears the marker outright
    (`clear_access_token_revocation`) instead of relying on a fresh login's
    `iat` to out-race a stale one here.
    """
    return revoked_at is not None and iat <= revoked_at


__all__ = [
    "GuestAccessExpired",
    "IssuedRefreshToken",
    "RefreshTokenReused",
    "access_tokens_revoked_at",
    "clear_access_token_revocation",
    "is_access_token_revoked",
    "issue_family",
    "revoke_access_tokens_for_user",
    "revoke_all_for_user",
    "revoke_family_for_token",
    "rotate",
]
