"""Authentication.

Login is deliberately uniform: the same response and comparable timing whether
or not the account exists. The learner list is the customer's client list, and
confirming that a named executive has an account is itself a disclosure.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.security import (
    hash_password,
    hash_token,
    new_recovery_code,
    new_token,
    verify_password,
    verify_totp,
)
from src.models.auth import MagicLink, MfaRecoveryCode, PasswordReset
from src.models.rbac import RoleAssignment, RolePermission
from src.models.user import User

LOCKOUT_THRESHOLD = 10
LOCKOUT_MINUTES = 15

MFA_LOCKOUT_THRESHOLD = 6
MFA_LOCKOUT_MINUTES = 15
RECOVERY_CODE_COUNT = 10

# Verified against a throwaway hash when the account does not exist, so a
# missing user costs the same wall-clock time as a wrong password.
_DUMMY_HASH = hash_password("timing-equalisation-only")


async def find_by_email(session: AsyncSession, crypto: CryptoBox, email: str) -> User | None:
    index = crypto.blind_index(email)
    stmt = select(User).where(User.email_blind_index == index).where(User.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def permissions_for(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    stmt = (
        select(RolePermission.permission_code)
        .join(RoleAssignment, RoleAssignment.role_code == RolePermission.role_code)
        .where(RoleAssignment.user_id == user_id)
        .distinct()
    )
    return sorted((await session.execute(stmt)).scalars().all())


def is_locked(user: User, *, now: datetime | None = None) -> bool:
    if user.locked_until is None:
        return False
    return user.locked_until > (now or datetime.now(UTC))


def display_name(user: User, crypto: CryptoBox) -> str:
    """The learner-facing name for a document (certificate, transcript) —
    `full_name_encrypted` when captured, else the email, which is a
    documented, honest fallback rather than a fabricated name for
    accounts guest/checkout flows never asked for a name."""
    if user.full_name_encrypted:
        return crypto.decrypt(user.full_name_encrypted)
    return crypto.decrypt(user.email_encrypted)


@dataclass(frozen=True, slots=True)
class DisplayIdentity:
    """What a greeting or an avatar needs, derived once. `full_name` and
    `first_name` are genuinely null for the many accounts checkout and
    guest flows never asked a name for — `initials` never is, because an
    avatar with nothing in it is a rendering bug, so it falls back to the
    email's local part rather than inventing a name (same honesty rule as
    `display_name` above)."""

    full_name: str | None
    first_name: str | None
    initials: str


def _initials_from(text_value: str) -> str:
    tokens = [t for t in text_value.replace(".", " ").replace("_", " ").split() if t]
    letters = [c for token in tokens for c in token[:1] if c.isalpha()]
    if len(letters) >= 2:
        return (letters[0] + letters[-1]).upper()
    alpha = [c for c in text_value if c.isalpha()]
    return "".join(alpha[:2]).upper() or "?"


def display_identity(user: User, crypto: CryptoBox) -> DisplayIdentity:
    full_name = crypto.decrypt(user.full_name_encrypted) if user.full_name_encrypted else None
    full_name = full_name.strip() if full_name else None
    if full_name:
        first_name = full_name.split()[0]
        return DisplayIdentity(
            full_name=full_name, first_name=first_name, initials=_initials_from(full_name)
        )
    local_part = crypto.decrypt(user.email_encrypted).split("@", 1)[0]
    return DisplayIdentity(full_name=None, first_name=None, initials=_initials_from(local_part))


def guest_days_left(user: User, *, now: datetime | None = None) -> int | None:
    """Whole days of guest access still to run — null for a non-guest or a
    guest with no expiry set. Never negative: an expired guest is `0`, and
    the two real enforcement points (`consume_magic_link`, `tokens.rotate`)
    are what actually cut access off, not this number."""
    if not user.is_guest or user.guest_expires_at is None:
        return None
    remaining = (user.guest_expires_at - (now or datetime.now(UTC))).total_seconds()
    return max(0, math.ceil(remaining / 86400))


async def authenticate(
    session: AsyncSession, crypto: CryptoBox, *, email: str, password: str
) -> User | None:
    """Return the user on success, None on any failure.

    Callers must not distinguish the failure reasons in their response.
    """
    user = await find_by_email(session, crypto, email)

    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None

    if is_locked(user) or user.status != "active":
        verify_password(password, _DUMMY_HASH)
        return None

    if user.password_hash is None or not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= LOCKOUT_THRESHOLD:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES)
        await session.flush()
        return None

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user


async def create_user(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    email: str,
    password: str | None = None,
    full_name: str | None = None,
    is_guest: bool = False,
    guest_days: int | None = None,
) -> User:
    normalised = email.strip().lower()
    user = User(
        tenant_id=tenant_id,
        email_encrypted=crypto.encrypt(normalised),
        email_blind_index=crypto.blind_index(normalised),
        email_domain=normalised.split("@", 1)[-1],
        full_name_encrypted=crypto.encrypt(full_name) if full_name else None,
        password_hash=hash_password(password) if password else None,
        is_guest=is_guest,
        guest_expires_at=(
            datetime.now(UTC) + timedelta(days=guest_days) if guest_days is not None else None
        ),
    )
    session.add(user)
    await session.flush()
    return user


async def create_magic_link(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, email: str, minutes: int
) -> str | None:
    """Returns the raw token, or None if there is no usable account.

    Callers must not let the two cases produce different responses or timing —
    POST /auth/magic-link always returns 204. See authenticate() above for the
    same rule applied to login.
    """
    user = await find_by_email(session, crypto, email)
    if user is None or user.status != "active" or user.deleted_at is not None:
        verify_password("timing-equalisation-only", _DUMMY_HASH)
        return None

    raw = new_token()
    session.add(
        MagicLink(
            tenant_id=tenant_id,
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
        )
    )
    await session.flush()
    return raw


async def consume_magic_link(session: AsyncSession, *, raw_token: str) -> User | None:
    """Single-use, atomically: the consuming UPDATE only matches an
    unconsumed, unexpired row, so a replayed link — including two requests
    racing on the same link — can win at most once.
    """
    now = datetime.now(UTC)
    stmt = text(
        "UPDATE magic_links SET consumed_at = :now "
        "WHERE token_hash = :h AND consumed_at IS NULL AND expires_at > :now "
        "RETURNING user_id"
    )
    row = (await session.execute(stmt, {"now": now, "h": hash_token(raw_token)})).first()
    if row is None:
        return None

    user = await session.get(User, row[0])
    if user is None or user.status != "active" or user.deleted_at is not None:
        return None
    if user.is_guest and user.guest_expires_at is not None and user.guest_expires_at <= now:
        return None
    return user


async def create_password_reset(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, email: str, minutes: int
) -> str | None:
    """Same contract as create_magic_link: raw token or None, and the caller
    must not let the two cases differ in response or timing."""
    user = await find_by_email(session, crypto, email)
    if user is None or user.status != "active" or user.deleted_at is not None:
        verify_password("timing-equalisation-only", _DUMMY_HASH)
        return None

    raw = new_token()
    session.add(
        PasswordReset(
            tenant_id=tenant_id,
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=minutes),
        )
    )
    await session.flush()
    return raw


async def consume_password_reset(
    session: AsyncSession, *, raw_token: str, new_password: str
) -> User | None:
    """Atomic single use, like consume_magic_link. On success the password is
    replaced and the login lockout cleared — the person just proved control
    of the mailbox, which is the same proof the lockout exists to demand.
    Revoking refresh-token families is the caller's job (tokens service)."""
    now = datetime.now(UTC)
    stmt = text(
        "UPDATE password_resets SET consumed_at = :now "
        "WHERE token_hash = :h AND consumed_at IS NULL AND expires_at > :now "
        "RETURNING user_id"
    )
    row = (await session.execute(stmt, {"now": now, "h": hash_token(raw_token)})).first()
    if row is None:
        return None

    user = await session.get(User, row[0])
    if user is None or user.status != "active" or user.deleted_at is not None:
        return None

    user.password_hash = hash_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    await session.flush()
    return user


def is_mfa_locked(user: User, *, now: datetime | None = None) -> bool:
    if user.mfa_locked_until is None:
        return False
    return user.mfa_locked_until > (now or datetime.now(UTC))


async def enroll_mfa(
    session: AsyncSession, crypto: CryptoBox, *, user: User, secret: str
) -> list[str]:
    """Persist a confirmed TOTP secret and issue recovery codes.

    Called only after the caller has already verified a live code against
    `secret` — this function does not verify, it commits. Regenerating wipes
    any prior codes, since they are invalidated as a set (04 §1.3).
    """
    user.mfa_secret_encrypted = crypto.encrypt(secret)
    user.mfa_enforced_at = datetime.now(UTC)
    user.mfa_failed_count = 0
    user.mfa_locked_until = None

    await session.execute(text("DELETE FROM mfa_recovery_codes WHERE user_id = :u"), {"u": user.id})
    codes = [new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        session.add(
            MfaRecoveryCode(
                tenant_id=user.tenant_id,
                user_id=user.id,
                code_hash=hash_token(code),
            )
        )
    await session.flush()
    return codes


async def verify_mfa_code(
    session: AsyncSession, crypto: CryptoBox, *, user: User, code: str
) -> bool:
    """TOTP first, then an unused recovery code. Tracks its own failure
    counter — separate from the password one, per the documented thresholds.
    """
    if user.mfa_secret_encrypted is not None:
        secret = crypto.decrypt(user.mfa_secret_encrypted)
        if verify_totp(secret=secret, code=code):
            user.mfa_failed_count = 0
            user.mfa_locked_until = None
            await session.flush()
            return True

    stmt = text(
        "UPDATE mfa_recovery_codes SET used_at = :now "
        "WHERE user_id = :u AND code_hash = :h AND used_at IS NULL "
        "RETURNING id"
    )
    won = (
        await session.execute(
            stmt, {"now": datetime.now(UTC), "u": user.id, "h": hash_token(code.strip().upper())}
        )
    ).first()
    if won is not None:
        user.mfa_failed_count = 0
        user.mfa_locked_until = None
        await session.flush()
        return True

    user.mfa_failed_count += 1
    if user.mfa_failed_count >= MFA_LOCKOUT_THRESHOLD:
        user.mfa_locked_until = datetime.now(UTC) + timedelta(minutes=MFA_LOCKOUT_MINUTES)
    await session.flush()
    return False


__all__ = [
    "LOCKOUT_MINUTES",
    "LOCKOUT_THRESHOLD",
    "MFA_LOCKOUT_MINUTES",
    "MFA_LOCKOUT_THRESHOLD",
    "RECOVERY_CODE_COUNT",
    "DisplayIdentity",
    "authenticate",
    "consume_magic_link",
    "consume_password_reset",
    "create_magic_link",
    "create_password_reset",
    "create_user",
    "display_identity",
    "display_name",
    "enroll_mfa",
    "find_by_email",
    "guest_days_left",
    "is_locked",
    "is_mfa_locked",
    "permissions_for",
    "verify_mfa_code",
]
