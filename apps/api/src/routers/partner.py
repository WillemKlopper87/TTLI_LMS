"""Partner portal routes (2026-09-11-partner-portal-design.md).

Minimal implementation of partner operations:
  - Partner profile creation
  - Activation status check and activation
  - Client organisation creation under a partner

Full portal routes (/partner/*) and admin integration are out of scope
for this slice and will be implemented after Sprint 1 hardening completes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from src.core.deps import AuditedSessionDep, PrincipalDep, SessionDep
from src.core.errors import AppError, NotFound
from src.models.partner import PartnerProfile
from src.schemas.partner import (
    ActivationStatusResponse,
    ClientOrgResponse,
    CreateClientOrgRequest,
    PartnerProfileCreateRequest,
    PartnerProfileResponse,
)
from src.services import partner as partner_service
from src.services.tenant_users import get_user

router = APIRouter(tags=["partner"], prefix="/partner")


@router.post(
    "/profiles",
    response_model=PartnerProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a partner profile for an organisation",
)
async def create_partner_profile(
    body: PartnerProfileCreateRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> PartnerProfileResponse:
    """Create a new partner profile.

    Initial status is 'invited'. Activation requires MFA, operator agreement,
    and (for health professionals) registration number.

    Requires the caller to be an admin member of the target organisation.
    """
    await partner_service.require_organisation_admin(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=body.organisation_id,
        user_id=principal.user_id,
    )
    try:
        profile = await partner_service.create_partner_profile(
            session,
            tenant_id=principal.tenant_id,
            organisation_id=body.organisation_id,
            display_name=body.display_name,
            bio=body.bio,
            logo_object_key=body.logo_object_key,
            professional_body=body.professional_body,
        )
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PartnerProfileResponse(
        id=profile.id,
        organisation_id=profile.organisation_id,
        display_name=profile.display_name,
        bio=profile.bio,
        logo_object_key=profile.logo_object_key,
        professional_body=profile.professional_body,
        status=profile.status,
        operator_agreement_accepted_at=(
            profile.operator_agreement_accepted_at.isoformat()
            if profile.operator_agreement_accepted_at
            else None
        ),
    )


@router.get(
    "/profiles/by-organisation/{organisation_id}",
    response_model=PartnerProfileResponse | None,
    summary="Fetch the partner profile for an organisation, if one exists",
)
async def get_partner_profile_for_organisation(
    organisation_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> PartnerProfileResponse | None:
    """Look up an organisation's partner profile.

    Returns null rather than 404 when no profile exists yet — the UI's
    create-vs-manage decision hinges on "does one exist", not on this
    being an error state.
    """
    profile = await partner_service.get_partner_profile(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=organisation_id,
    )
    if profile is None:
        return None
    return PartnerProfileResponse(
        id=profile.id,
        organisation_id=profile.organisation_id,
        display_name=profile.display_name,
        bio=profile.bio,
        logo_object_key=profile.logo_object_key,
        professional_body=profile.professional_body,
        status=profile.status,
        operator_agreement_accepted_at=(
            profile.operator_agreement_accepted_at.isoformat()
            if profile.operator_agreement_accepted_at
            else None
        ),
    )


@router.get(
    "/profiles/{profile_id}/activation-status",
    response_model=ActivationStatusResponse,
    summary="Check activation status of a partner profile",
)
async def check_activation_status(
    profile_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> ActivationStatusResponse:
    """Check whether a partner profile can be activated.

    Returns:
        - can_activate: True if all gates are met
        - missing_gates: List of gates that are not yet cleared
    """
    profile = (
        await session.execute(
            select(PartnerProfile).where(
                PartnerProfile.id == profile_id,
                PartnerProfile.tenant_id == principal.tenant_id,
            )
        )
    ).scalar_one_or_none()

    if profile is None:
        raise NotFound("Partner profile not found")

    # Get the user to check MFA
    user = await get_user(session, tenant_id=principal.tenant_id, user_id=principal.user_id)
    if user is None:
        raise NotFound("User not found")

    missing_gates = []
    if profile.operator_agreement_accepted_at is None:
        missing_gates.append("operator agreement not accepted")
    if user.mfa_secret_encrypted is None:
        missing_gates.append("MFA not enrolled")
    if profile.professional_body is not None and profile.registration_number_encrypted is None:
        missing_gates.append("registration number required for health professionals")

    can_activate = len(missing_gates) == 0
    return ActivationStatusResponse(can_activate=can_activate, missing_gates=missing_gates)


@router.post(
    "/profiles/{profile_id}/activate",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Activate a partner profile",
)
async def activate_profile(
    profile_id: uuid.UUID,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> None:
    """Activate a partner profile if all gates are cleared.

    Raises AppError if any gate is not met.
    """
    profile = (
        await session.execute(
            select(PartnerProfile).where(
                PartnerProfile.id == profile_id,
                PartnerProfile.tenant_id == principal.tenant_id,
            )
        )
    ).scalar_one_or_none()

    if profile is None:
        raise NotFound("Partner profile not found")

    await partner_service.require_organisation_admin(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=profile.organisation_id,
        user_id=principal.user_id,
    )

    user = await get_user(session, tenant_id=principal.tenant_id, user_id=principal.user_id)
    if user is None:
        raise NotFound("User not found")

    try:
        await partner_service.activate_partner(session, profile=profile, user=user)
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/clients",
    response_model=ClientOrgResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a client organisation under the authenticated partner",
)
async def create_client_org(
    body: CreateClientOrgRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ClientOrgResponse:
    """Create a new client organisation under a partner.

    The partner organisation is resolved from the caller's own admin
    membership — a caller who does not administer any partner organisation
    cannot create client organisations. Future versions will support
    explicit parent selection among multiple partners.
    """
    parent = await partner_service.get_admin_partner_organisation(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    if parent is None:
        raise NotFound("No partner organisation administered by this user")

    try:
        org = await partner_service.create_client_organisation(
            session,
            tenant_id=principal.tenant_id,
            parent_organisation_id=parent.id,
            name=body.name,
        )
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ClientOrgResponse(
        id=org.id,
        name=org.name,
        kind=org.kind,
        parent_organisation_id=org.parent_organisation_id,
    )


__all__ = ["router"]
