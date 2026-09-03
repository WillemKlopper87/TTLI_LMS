"""Staff administration: who is in this tenant, and what they may do
(`docs/BACKLOG.md` P3 — the "unlisted" gap in the feature-matrix audit).

Until now there was no way to create a colleague or give them a role
from inside the product. `role_assignments` rows were written by
migration `0002` for the demo tenants and by test fixtures, and by
nothing else — which is why `AuditAction.ROLE_ASSIGNED` has existed
since 0001 with no code path that could ever emit it.

**The escalation rule is the load-bearing part of this module.** Role
assignment is the one operation in the platform that can change what its
own caller is allowed to do next, so two invariants are enforced here
rather than left to the permission gate:

1. **You may only grant a role whose permissions you already hold.** An
   `admin` holding `user:invite` cannot mint a `super_admin` and then
   act through them. Without this, "can administer users" silently means
   "can become anyone", and the whole permission model is decorative.
2. **You may not change your own roles.** Not because a granter could
   escalate through it — rule 1 already prevents that — but because the
   reverse mistake is unrecoverable: revoking your own last
   `tenant:manage` locks the tenant out of its own administration with
   no in-product way back.

Emails are returned in full here, unlike the operations dashboard which
masks them. The difference is the job: an operations reader needs to
know *that* a learner is stalling, while someone administering accounts
must be able to tell two colleagues apart and type the right address
into a support ticket. `user:invite` is the gate on that.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, Forbidden
from src.models.rbac import Role, RoleAssignment, RolePermission
from src.models.user import User
from src.schemas.tenant_users import RoleSummary, TenantUserRow
from src.services import tokens

ACTIVE = "active"
SUSPENDED = "suspended"


async def list_roles(session: AsyncSession) -> list[RoleSummary]:
    """Every role with the permissions behind it, so the admin screen can
    say what a choice *means* rather than showing an opaque code."""
    roles = (await session.execute(select(Role).order_by(Role.code))).scalars().all()
    grants = (
        await session.execute(
            select(RolePermission.role_code, RolePermission.permission_code).order_by(
                RolePermission.role_code, RolePermission.permission_code
            )
        )
    ).all()
    by_role: dict[str, list[str]] = {}
    for role_code, permission in grants:
        by_role.setdefault(role_code, []).append(permission)
    return [
        RoleSummary(code=role.code, name=role.name, permissions=by_role.get(role.code, []))
        for role in roles
    ]


async def permissions_of_role(session: AsyncSession, role_code: str) -> set[str]:
    return set(
        (
            await session.execute(
                select(RolePermission.permission_code).where(RolePermission.role_code == role_code)
            )
        )
        .scalars()
        .all()
    )


async def assert_can_grant(
    session: AsyncSession, *, role_code: str, actor_permissions: frozenset[str]
) -> None:
    """Invariant 1. A caller may only hand out authority they already
    have; anything else is escalation wearing an admin screen."""
    exists = (
        await session.execute(select(Role.code).where(Role.code == role_code))
    ).scalar_one_or_none()
    if exists is None:
        raise AppError("No such role.", {"role_code": role_code})

    granted = await permissions_of_role(session, role_code)
    missing = sorted(granted - set(actor_permissions))
    if missing:
        raise Forbidden(
            "You cannot grant a role that carries permissions you do not hold yourself."
        )


async def list_users(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    include_learners: bool = False,
    limit: int = 200,
) -> list[TenantUserRow]:
    """Staff first. A tenant's learner list runs to thousands and belongs
    on a reporting screen with its own filters; this one exists to answer
    "who can do things here", so it returns role-holders unless the
    caller explicitly asks for everyone."""
    users = (
        (
            await session.execute(
                select(User)
                .where(User.tenant_id == tenant_id)
                .order_by(User.created_at.desc())
                .limit(limit if include_learners else 2000)
            )
        )
        .scalars()
        .all()
    )
    assignments = (
        await session.execute(
            select(RoleAssignment.user_id, RoleAssignment.role_code).where(
                RoleAssignment.tenant_id == tenant_id
            )
        )
    ).all()
    roles_by_user: dict[uuid.UUID, list[str]] = {}
    for user_id, role_code in assignments:
        roles_by_user.setdefault(user_id, []).append(role_code)

    rows: list[TenantUserRow] = []
    for user in users:
        roles = sorted(roles_by_user.get(user.id, []))
        if not include_learners and not roles:
            continue
        rows.append(
            TenantUserRow(
                id=user.id,
                email=_email(crypto, user),
                full_name=_name(crypto, user),
                status=user.status,
                is_guest=user.is_guest,
                roles=roles,
                created_at=user.created_at,
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _email(crypto: CryptoBox, user: User) -> str:
    try:
        return crypto.decrypt(user.email_encrypted)
    except Exception:
        # A rotated key must not make an account unmanageable — the admin
        # can still suspend or re-role a row they cannot read the address
        # of (docs/STATUS.md §10).
        return "(unreadable — key rotated)"


def _name(crypto: CryptoBox, user: User) -> str | None:
    if user.full_name_encrypted is None:
        return None
    try:
        return crypto.decrypt(user.full_name_encrypted)
    except Exception:
        return None


async def get_user(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> User | None:
    return (
        await session.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def assign_role(
    session: AsyncSession, *, tenant_id: uuid.UUID, user: User, role_code: str
) -> bool:
    """Idempotent: granting a role twice is not an error, it is a no-op.
    Returns whether anything changed, so the caller only writes an audit
    row for a real change."""
    existing = (
        await session.execute(
            select(RoleAssignment.id).where(
                RoleAssignment.tenant_id == tenant_id,
                RoleAssignment.user_id == user.id,
                RoleAssignment.role_code == role_code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    session.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role_code))
    await session.flush()
    return True


async def revoke_role(
    session: AsyncSession, *, tenant_id: uuid.UUID, user: User, role_code: str
) -> bool:
    # Read first rather than trusting DELETE's rowcount: the caller only
    # writes an audit row for a real change, and SQLAlchemy's typed
    # Result does not promise rowcount on every backend.
    existing = (
        await session.execute(
            select(RoleAssignment.id).where(
                RoleAssignment.tenant_id == tenant_id,
                RoleAssignment.user_id == user.id,
                RoleAssignment.role_code == role_code,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    await session.execute(delete(RoleAssignment).where(RoleAssignment.id == existing))
    await session.flush()
    return True


async def set_status(
    session: AsyncSession,
    *,
    user: User,
    status: str,
    redis: Redis,
    access_token_ttl_seconds: int,
) -> None:
    """Flip the status row, and — moving to anything but active — end every
    session the account currently holds.

    Without this, suspension was cosmetic: the row said "suspended" but a
    refresh token kept rotating and an already-issued access token kept
    working until it happened to expire (fable5.1_review.md H-11). Both
    halves live here, at the one state transition, rather than left to
    callers to remember: the refresh-token families in the database
    (`revoke_all_for_user`), and the access tokens already handed out, which
    exist only as signed JWTs with no row to flip (`revoke_access_tokens_
    for_user` marks a cutoff in Redis that `core/deps.get_principal` checks
    on every request instead).
    """
    if status not in (ACTIVE, SUSPENDED):
        raise AppError("Status must be active or suspended.", {"status": status})
    user.status = status
    user.updated_at = datetime.now(UTC)
    await session.flush()
    if status != ACTIVE:
        await tokens.revoke_all_for_user(session, user_id=user.id)
        await tokens.revoke_access_tokens_for_user(
            redis, user_id=user.id, ttl_seconds=access_token_ttl_seconds
        )


__all__ = [
    "ACTIVE",
    "SUSPENDED",
    "assert_can_grant",
    "assign_role",
    "get_user",
    "list_roles",
    "list_users",
    "permissions_of_role",
    "revoke_role",
    "set_status",
]
