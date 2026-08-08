"""Authentication.

Login is deliberately uniform: the same response and comparable timing whether
or not the account exists. The learner list is the customer's client list, and
confirming that a named executive has an account is itself a disclosure.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.security import hash_password, verify_password
from src.models.rbac import RoleAssignment, RolePermission
from src.models.user import User

LOCKOUT_THRESHOLD = 10
LOCKOUT_MINUTES = 15
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


__all__ = [
    "LOCKOUT_MINUTES",
    "LOCKOUT_THRESHOLD",
    "authenticate",
    "create_user",
    "find_by_email",
    "is_locked",
    "permissions_for",
]
