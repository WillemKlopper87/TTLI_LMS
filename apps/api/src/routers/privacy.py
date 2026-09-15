"""Data-subject rights (BACKLOG T12, 04_SECURITY_AND_COMPLIANCE.md §5.3).

Self-service rights live under `/me/privacy/*`; admin-mediated legal-hold and
erasure actions reuse the existing `user:suspend` permission. Export downloads
use a high-entropy five-minute capability and therefore do not require a second
authentication round-trip; the capability is deleted after the first download.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from src.core.deps import (
    AuditedSessionDep,
    CryptoDep,
    PrincipalDep,
    RedisDep,
    SessionDep,
    SettingsDep,
)
from src.core.errors import AppError, NotFound
from src.schemas.privacy import (
    ConsentRequest,
    DataExportResponse,
    EraseAccountRequest,
    LegalHoldRequest,
    LegalHoldStatusResponse,
)
from src.services import consent as consent_service
from src.services import privacy
from src.services.tenant_users import get_user

router = APIRouter(tags=["privacy"])

CONSENT_PURPOSES = {"marketing", "analytics", "ai_processing"}
POLICY_VERSION = "unpublished-0"
SUSPEND = "user:suspend"


@router.post(
    "/me/privacy/export",
    response_model=DataExportResponse,
    summary="Export your personal data (POPIA access / portability)",
)
async def export_my_data(
    principal: PrincipalDep,
    session: AuditedSessionDep,
    crypto: CryptoDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> DataExportResponse:
    user = await get_user(session, tenant_id=principal.tenant_id, user_id=principal.user_id)
    if user is None:
        raise NotFound("No such user.")
    url = await privacy.build_export(
        session,
        crypto,
        redis,
        user=user,
        api_public_url=settings.api_public_url,
    )
    return DataExportResponse(
        download_url=url, expires_in_seconds=privacy.EXPORT_EXPIRES_IN_SECONDS
    )


@router.get(
    "/privacy/export-download",
    response_class=Response,
    summary="Download a short-lived personal-data export capability",
)
async def download_privacy_export(
    redis: RedisDep,
    token: str = Query(..., min_length=32, max_length=128),
) -> Response:
    body = await privacy.consume_export(redis, token=token)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="ttli-personal-data.json"',
        },
    )


@router.post(
    "/me/privacy/erase",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Erase your account (POPIA deletion — anonymisation, not row deletion)",
)
async def erase_my_account(
    body: EraseAccountRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
    crypto: CryptoDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> None:
    if not body.confirm:
        raise AppError("Set confirm to true to erase your account.")
    user = await get_user(session, tenant_id=principal.tenant_id, user_id=principal.user_id)
    if user is None:
        raise NotFound("No such user.")
    await privacy.erase_user(
        session,
        crypto,
        redis,
        user=user,
        actor_user_id=principal.user_id,
        access_token_ttl_seconds=settings.access_token_minutes * 60,
    )


@router.post(
    "/me/privacy/consent",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Grant or withdraw consent for a purpose",
)
async def set_my_consent(
    body: ConsentRequest, principal: PrincipalDep, session: SessionDep
) -> None:
    if body.purpose not in CONSENT_PURPOSES:
        raise AppError("Unknown consent purpose.", {"purpose": body.purpose})
    await consent_service.record(
        session,
        tenant_id=principal.tenant_id,
        purpose=body.purpose,  # type: ignore[arg-type]
        granted=body.granted,
        source="self_service",
        policy_version=POLICY_VERSION,
        user_id=principal.user_id,
    )


@router.post(
    "/admin/users/{user_id}/legal-hold",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Place an account under legal hold, blocking erasure",
)
async def place_legal_hold(
    user_id: uuid.UUID, body: LegalHoldRequest, principal: PrincipalDep, session: AuditedSessionDep
) -> None:
    principal.require(SUSPEND)
    user = await get_user(session, tenant_id=principal.tenant_id, user_id=user_id)
    if user is None:
        raise NotFound("No such user.")
    await privacy.set_legal_hold(
        session, user=user, reason=body.reason, actor_user_id=principal.user_id
    )


@router.delete(
    "/admin/users/{user_id}/legal-hold",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Clear a legal hold",
)
async def release_legal_hold(
    user_id: uuid.UUID, principal: PrincipalDep, session: AuditedSessionDep
) -> None:
    principal.require(SUSPEND)
    user = await get_user(session, tenant_id=principal.tenant_id, user_id=user_id)
    if user is None:
        raise NotFound("No such user.")
    await privacy.clear_legal_hold(session, user=user, actor_user_id=principal.user_id)


@router.get(
    "/admin/users/{user_id}/legal-hold",
    response_model=LegalHoldStatusResponse,
    summary="Read an account's legal-hold status",
)
async def get_legal_hold(
    user_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> LegalHoldStatusResponse:
    principal.require(SUSPEND)
    user = await get_user(session, tenant_id=principal.tenant_id, user_id=user_id)
    if user is None:
        raise NotFound("No such user.")
    return LegalHoldStatusResponse(
        legal_hold=user.legal_hold,
        legal_hold_reason=user.legal_hold_reason,
        legal_hold_set_at=user.legal_hold_set_at.isoformat() if user.legal_hold_set_at else None,
    )


@router.post(
    "/admin/users/{user_id}/privacy/erase",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Admin-initiated erasure, for a support-handled request",
)
async def admin_erase_user(
    user_id: uuid.UUID,
    principal: PrincipalDep,
    session: AuditedSessionDep,
    crypto: CryptoDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> None:
    principal.require(SUSPEND)
    user = await get_user(session, tenant_id=principal.tenant_id, user_id=user_id)
    if user is None:
        raise NotFound("No such user.")
    await privacy.erase_user(
        session,
        crypto,
        redis,
        user=user,
        actor_user_id=principal.user_id,
        access_token_ttl_seconds=settings.access_token_minutes * 60,
    )


__all__ = ["router"]
