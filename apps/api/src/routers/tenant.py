"""Tenant-facing metadata: the resolved tenant's public theme.

Public by design — the login page needs the palette before anyone is
authenticated. RLS still applies: the session is bound to the resolved
tenant, so the query can only ever see that tenant's row.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from src.core.deps import PrincipalDep, SessionDep, TenantDep
from src.core.errors import NotFound
from src.models.audit import AuditAction
from src.models.tenant import Tenant
from src.models.theme import TenantTheme
from src.services import audit

router = APIRouter(prefix="/tenant", tags=["tenant"])


class ThemeResponse(BaseModel):
    tenant_slug: str
    tenant_name: str
    logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    login_background_url: str | None = None
    support_email: str | None = None


@router.get("/theme", response_model=ThemeResponse, summary="The resolved tenant's public theme")
async def theme(session: SessionDep, tenant: TenantDep) -> ThemeResponse:
    row = (
        await session.execute(select(TenantTheme).where(TenantTheme.tenant_id == tenant.id))
    ).scalar_one_or_none()
    return ThemeResponse(
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        logo_url=row.logo_url if row else None,
        primary_color=row.primary_color if row else None,
        secondary_color=row.secondary_color if row else None,
        login_background_url=row.login_background_url if row else None,
        support_email=row.support_email if row else None,
    )


class ManagerVisibilitySettingRequest(BaseModel):
    allow_manager_individual_results: bool


class ManagerVisibilitySettingResponse(BaseModel):
    allow_manager_individual_results: bool


@router.get(
    "/settings/manager-visibility",
    response_model=ManagerVisibilitySettingResponse,
    summary="REQ-TEN-03's tenant-level toggle, current value",
)
async def get_manager_visibility_setting(
    principal: PrincipalDep, session: SessionDep
) -> ManagerVisibilitySettingResponse:
    principal.require("tenant:manage")
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:  # pragma: no cover - the request already resolved this tenant
        raise NotFound("No such tenant.")
    return ManagerVisibilitySettingResponse(
        allow_manager_individual_results=bool(
            tenant.settings.get("allow_manager_individual_results", False)
        )
    )


@router.patch(
    "/settings/manager-visibility",
    response_model=ManagerVisibilitySettingResponse,
    summary="REQ-TEN-03's tenant-level toggle",
)
async def update_manager_visibility_setting(
    body: ManagerVisibilitySettingRequest, principal: PrincipalDep, session: SessionDep
) -> ManagerVisibilitySettingResponse:
    """The second of REQ-TEN-03's three conditions — a tenant admin's
    own toggle, independent of any single course's setting. Merges into
    the existing `settings` jsonb rather than overwriting it, since
    other keys may already live there."""
    principal.require("tenant:manage")
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:  # pragma: no cover - the request already resolved this tenant
        raise NotFound("No such tenant.")
    before = tenant.settings.get("allow_manager_individual_results")
    tenant.settings = {
        **tenant.settings,
        "allow_manager_individual_results": body.allow_manager_individual_results,
    }
    flag_modified(tenant, "settings")
    await session.flush()
    # A tenant-wide privacy toggle: exactly the kind of change a
    # compliance reviewer needs attributed and dated (Pass B).
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.TENANT_SETTING_CHANGED,
        actor_user_id=principal.user_id,
        entity_type="tenant",
        entity_id=principal.tenant_id,
        before={"allow_manager_individual_results": before},
        after={"allow_manager_individual_results": body.allow_manager_individual_results},
    )
    return ManagerVisibilitySettingResponse(
        allow_manager_individual_results=tenant.settings["allow_manager_individual_results"]
    )


__all__ = ["ManagerVisibilitySettingResponse", "ThemeResponse", "router"]
