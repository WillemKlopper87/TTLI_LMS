"""Super-admin-only platform operations: feature flags and a system
health summary. Gated on `settings:manage` — seeded in the baseline
permission set (alembic/versions/0002_seed_roles_and_tenants.py),
granted only to super_admin, never checked anywhere until now. The
business-facing `admin` role does not hold this permission (it isn't in
that role's list either) — the split this exists for: routine tenant
configuration stays under `/admin/settings` (`tenant:manage`), platform-
level maintenance concerns — the things a business admin shouldn't be
able to touch or even see — live here instead.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter
from sqlalchemy import text

from src.core.deps import PrincipalDep, SessionDep, SettingsDep
from src.core.redis import get_redis
from src.schemas.platform import (
    FeatureFlagInfo,
    FeatureFlagsResponse,
    ServiceStatus,
    SetFeatureFlagRequest,
    SystemHealthResponse,
)
from src.services import feature_flags as feature_flags_service

router = APIRouter(prefix="/platform", tags=["platform"])
PERMISSION = "settings:manage"


def _response(current: dict[str, bool]) -> FeatureFlagsResponse:
    return FeatureFlagsResponse(
        flags=[
            FeatureFlagInfo(
                key=f.key, label=f.label, description=f.description, enabled=current[f.key]
            )
            for f in feature_flags_service.KNOWN_FLAGS
        ]
    )


@router.get("/feature-flags", response_model=FeatureFlagsResponse)
async def list_feature_flags(principal: PrincipalDep, session: SessionDep) -> FeatureFlagsResponse:
    principal.require(PERMISSION)
    current = await feature_flags_service.get_flags(session, tenant_id=principal.tenant_id)
    return _response(current)


@router.patch("/feature-flags/{key}", response_model=FeatureFlagsResponse)
async def set_feature_flag(
    key: str, body: SetFeatureFlagRequest, principal: PrincipalDep, session: SessionDep
) -> FeatureFlagsResponse:
    principal.require(PERMISSION)
    current = await feature_flags_service.set_flag(
        session, tenant_id=principal.tenant_id, flag=key, enabled=body.enabled
    )
    return _response(current)


@router.get("/system-health", response_model=SystemHealthResponse)
async def system_health(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> SystemHealthResponse:
    principal.require(PERMISSION)
    services: list[ServiceStatus] = []

    try:
        await session.execute(text("SELECT 1"))
        services.append(ServiceStatus(name="database", ok=True))
    except Exception as exc:
        services.append(ServiceStatus(name="database", ok=False, detail=str(exc)))

    try:
        redis = get_redis()
        start = time.monotonic()
        await redis.ping()
        elapsed_ms = (time.monotonic() - start) * 1000
        services.append(ServiceStatus(name="redis", ok=True, detail=f"{elapsed_ms:.0f}ms"))
    except Exception as exc:
        services.append(ServiceStatus(name="redis", ok=False, detail=str(exc)))

    return SystemHealthResponse(
        api_version=os.environ.get("APP_VERSION", "unknown"),
        environment=settings.environment,
        services=services,
    )


__all__ = ["router"]
