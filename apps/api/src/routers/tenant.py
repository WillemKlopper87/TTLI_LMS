"""Tenant-facing metadata: the resolved tenant's public theme.

Public by design — the login page needs the palette before anyone is
authenticated. RLS still applies: the session is bound to the resolved
tenant, so the query can only ever see that tenant's row.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from src.core.deps import SessionDep, TenantDep
from src.models.theme import TenantTheme

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


__all__ = ["ThemeResponse", "router"]
