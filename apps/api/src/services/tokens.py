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
    consume_stmt = text(
        "UPDATE refresh_tokens SET consumed_at = :now "
        "WHERE token_hash = :h AND consumed_at IS NULL AND revoked_at IS NULL "
        "AND expires_at > :now "
        "RETURNING user_id, family_id, device_fingerprint"
    )
    won = (await session.execute(consume_stmt, {"now": now, "h": token_hash})).first()

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
    ).where(RefreshToken.token_hash == token_hash)
    existing = (await session.execute(lookup_stmt)).first()

    if existing is None:
        raise RefreshTokenReused("no such token")
    reused_user_id, family_id, consumed_at, revoked_at = existing
    if revoked_at is None and consumed_at is not None:
        await _revoke_family(session, family_id=family_id)
        raise RefreshTokenReused("token already consumed", user_id=reused_user_id)
    raise RefreshTokenReused("token family already revoked or expired", user_id=reused_user_id)


async def _revoke_family(session: AsyncSession, *, family_id: uuid.UUID) -> None:
    stmt = select(RefreshToken).where(RefreshToken.family_id == family_id)
    rows = (await session.execute(stmt)).scalars().all()
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    await session.flush()


__all__ = ["IssuedRefreshToken", "RefreshTokenReused", "issue_family", "rotate"]
