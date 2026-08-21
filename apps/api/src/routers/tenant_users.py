"""Staff administration (`docs/BACKLOG.md` P3, feature-matrix "unlisted"
gap): list the people in a tenant, invite one, give and take roles,
suspend and reinstate.

Before this, `role_assignments` was written only by migration `0002` and
by test fixtures. There was no way to onboard a colleague without a
developer, and `AuditAction.ROLE_ASSIGNED` — defined since 0001 — had
never been emitted by anything.

**Permissions are split by blast radius, not by screen.**

* `user:invite` — create an account, list who exists. `admin` holds it.
* `user:suspend` — take someone's access away. `admin` holds it.
* `tenant:manage` — change what someone may *do*. Only `super_admin`
  holds it, because role assignment is the one operation that can change
  the caller's own authority, and it is additionally bounded by the
  no-escalation rule in `services/tenant_users.py`.

Every role change and status change writes an audit row. That is the
whole point of having had those action constants sitting unused.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import (
    AuditedSessionDep,
    CryptoDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    TenantDep,
)
from src.core.errors import AppError, Forbidden, NotFound
from src.models.audit import AuditAction
from src.schemas.tenant_users import (
    InviteUserRequest,
    RoleChangeRequest,
    RolesResponse,
    StatusChangeRequest,
    TenantUserRow,
    TenantUsersResponse,
)
from src.services import audit, identity
from src.services import tenant_users as people
from src.services.email import send_email

router = APIRouter(prefix="/tenant", tags=["tenant"])

INVITE = "user:invite"
SUSPEND = "user:suspend"
MANAGE_ROLES = "tenant:manage"


@router.get("/roles", response_model=RolesResponse, summary="Roles and the permissions they carry")
async def list_roles(principal: PrincipalDep, session: SessionDep) -> RolesResponse:
    principal.require(INVITE)
    return RolesResponse(roles=await people.list_roles(session))


@router.get(
    "/users",
    response_model=TenantUsersResponse,
    summary="Staff in this tenant; add include_learners=true for everyone",
)
async def list_users(
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    include_learners: bool = False,
) -> TenantUsersResponse:
    principal.require(INVITE)
    return TenantUsersResponse(
        items=await people.list_users(
            session,
            crypto,
            tenant_id=principal.tenant_id,
            include_learners=include_learners,
        )
    )


@router.post(
    "/users",
    response_model=TenantUserRow,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a colleague — creates the account and emails a sign-in link",
)
async def invite_user(
    body: InviteUserRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> TenantUserRow:
    """No password is set. The invitee arrives through a magic link and
    chooses their own credentials, so an administrator never handles
    someone else's password — the same reasoning `auth/password-reset`
    already follows.
    """
    principal.require(INVITE)

    if body.roles:
        principal.require(MANAGE_ROLES)
        for role_code in body.roles:
            await people.assert_can_grant(
                session, role_code=role_code, actor_permissions=principal.permissions
            )

    email = str(body.email).strip().lower()
    if await identity.find_by_email(session, crypto, email) is not None:
        raise AppError("Someone with that address already has an account here.")

    user = await identity.create_user(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        email=email,
        full_name=body.full_name,
    )
    for role_code in body.roles:
        if await people.assign_role(
            session, tenant_id=principal.tenant_id, user=user, role_code=role_code
        ):
            await _record_role(session, principal, user.id, role_code, granted=True)

    # Same shape as POST /auth/magic-link, including its "no usable
    # account" None case — which cannot arise here, the account was
    # created a line ago, but is handled rather than assumed away.
    raw = await identity.create_magic_link(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        email=email,
        minutes=settings.magic_link_minutes,
    )
    if raw is not None:
        link = f"https://{tenant.hostname}/auth/magic-link?token={raw}"
        await send_email(
            settings,
            to=email,
            subject=f"You have been invited to {tenant.name}",
            body=(
                f"An administrator has given you access to {tenant.name}.\n\n"
                f"Sign in with this link (valid {settings.magic_link_minutes} minutes):\n\n"
                f"{link}\n\n"
                "If it has expired, request a new one from the sign-in page."
            ),
        )

    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="user",
        entity_id=user.id,
        after={"invited": email, "roles": body.roles},
    )

    rows = await people.list_users(
        session, crypto, tenant_id=principal.tenant_id, include_learners=True
    )
    for row in rows:
        if row.id == user.id:
            return row
    raise NotFound("The invited account could not be read back.")


def _guard_not_self(principal: PrincipalDep, user_id: uuid.UUID) -> None:
    """Changing your own authority is refused in both directions.

    Granting to yourself is already bounded by the no-escalation rule, so
    this is really about the other mistake: revoking your own last
    `tenant:manage` leaves the tenant with no one who can administer it
    and no in-product way back.
    """
    if user_id == principal.user_id:
        raise Forbidden("Ask another administrator to change your own roles or status.")


@router.post(
    "/users/{user_id}/roles",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Grant a role — never one carrying permissions you lack yourself",
)
async def grant_role(
    user_id: uuid.UUID,
    body: RoleChangeRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> None:
    principal.require(MANAGE_ROLES)
    _guard_not_self(principal, user_id)
    await people.assert_can_grant(
        session, role_code=body.role_code, actor_permissions=principal.permissions
    )

    user = await people.get_user(session, tenant_id=principal.tenant_id, user_id=user_id)
    if user is None:
        raise NotFound("No such user.")
    if await people.assign_role(
        session, tenant_id=principal.tenant_id, user=user, role_code=body.role_code
    ):
        await _record_role(session, principal, user.id, body.role_code, granted=True)


@router.delete(
    "/users/{user_id}/roles/{role_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke a role",
)
async def revoke_role(
    user_id: uuid.UUID,
    role_code: str,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> None:
    principal.require(MANAGE_ROLES)
    _guard_not_self(principal, user_id)

    user = await people.get_user(session, tenant_id=principal.tenant_id, user_id=user_id)
    if user is None:
        raise NotFound("No such user.")
    if await people.revoke_role(
        session, tenant_id=principal.tenant_id, user=user, role_code=role_code
    ):
        await _record_role(session, principal, user.id, role_code, granted=False)


@router.post(
    "/users/{user_id}/status",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Suspend or reinstate an account",
)
async def change_status(
    user_id: uuid.UUID,
    body: StatusChangeRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> None:
    principal.require(SUSPEND)
    _guard_not_self(principal, user_id)

    user = await people.get_user(session, tenant_id=principal.tenant_id, user_id=user_id)
    if user is None:
        raise NotFound("No such user.")
    before = user.status
    await people.set_status(session, user=user, status=body.status)
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="user",
        entity_id=user.id,
        before={"status": before},
        after={"status": body.status},
    )


async def _record_role(
    session: AuditedSessionDep,
    principal: PrincipalDep,
    user_id: uuid.UUID,
    role_code: str,
    *,
    granted: bool,
) -> None:
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.ROLE_ASSIGNED if granted else AuditAction.ROLE_REVOKED,
        actor_user_id=principal.user_id,
        entity_type="user",
        entity_id=user_id,
        after={"role_code": role_code},
    )


__all__ = ["router"]
