"""Facilitator licensing: grant and list licences and seat grants.

API surface for managing licences: create a licence (tenant:manage | invoice:create),
list licences (tenant:manage | org admin), grant seats, and list seat grants (org admin).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import AuditedSessionDep, PrincipalDep, SessionDep
from src.core.errors import NotFound
from src.models.licence import Licence
from src.schemas.licence import (
    CreateLicenceRequest,
    GrantSeatRequest,
    LicenceResponse,
    ListLicencesResponse,
    ListSeatGrantsResponse,
    SeatGrantResponse,
)
from src.services import licence as licence_service

router = APIRouter(tags=["licences"])

MANAGE_LICENCES = "tenant:manage"
CREATE_INVOICES = "invoice:create"


def _licence_to_response(licence: Licence) -> LicenceResponse:
    return LicenceResponse(
        id=str(licence.id),
        organisation_id=str(licence.organisation_id),
        course_id=str(licence.course_id) if licence.course_id else None,
        learning_path_id=str(licence.learning_path_id) if licence.learning_path_id else None,
        status=licence.status,
        seats_purchased=licence.seats_purchased,
        seats_used=licence.seats_used,
        starts_at=licence.starts_at.isoformat(),
        ends_at=licence.ends_at.isoformat(),
        price_per_seat_cents=licence.price_per_seat_cents,
        currency=licence.currency,
        royalty_pct=float(licence.royalty_pct) if licence.royalty_pct else None,
        order_id=str(licence.order_id) if licence.order_id else None,
        notes=licence.notes,
        created_at=licence.created_at.isoformat(),
        updated_at=licence.updated_at.isoformat(),
    )


@router.post(
    "/licences",
    response_model=LicenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new licence",
)
async def create_licence(
    body: CreateLicenceRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> LicenceResponse:
    """Create a licence granting a course or learning path to a licensee organisation."""
    principal.require(MANAGE_LICENCES)

    licence = await licence_service.create_licence(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=uuid.UUID(body.organisation_id),
        course_id=uuid.UUID(body.course_id) if body.course_id else None,
        learning_path_id=uuid.UUID(body.learning_path_id) if body.learning_path_id else None,
        seats_purchased=body.seats_purchased,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        price_per_seat_cents=body.price_per_seat_cents,
        currency=body.currency,
        royalty_pct=body.royalty_pct,
        order_id=uuid.UUID(body.order_id) if body.order_id else None,
        notes=body.notes,
        actor_user_id=principal.user_id,
    )

    return _licence_to_response(licence)


@router.get(
    "/licences",
    response_model=ListLicencesResponse,
    summary="List licences for an organisation",
)
async def list_licences(
    organisation_id: str,
    principal: PrincipalDep,
    session: SessionDep,
) -> ListLicencesResponse:
    """List all licences for an organisation.

    Query parameter: organisation_id (UUID of the licensee organisation).
    """
    principal.require(MANAGE_LICENCES)

    licences = await licence_service.list_organisation_licences(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=uuid.UUID(organisation_id),
    )

    return ListLicencesResponse(items=[_licence_to_response(lic) for lic in licences])


@router.post(
    "/licences/{licence_id}/grant-seat",
    response_model=SeatGrantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a seat under a licence to a learner",
)
async def grant_seat(
    licence_id: str,
    body: GrantSeatRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> SeatGrantResponse:
    """Grant a seat under a licence to a learner.

    The learner can then enrol in courses/paths licensed under this licence.
    """
    principal.require(MANAGE_LICENCES)

    # Verify the licence exists and belongs to this tenant
    licence = await licence_service.get_active_licence(
        session,
        tenant_id=principal.tenant_id,
        licence_id=uuid.UUID(licence_id),
    )
    if licence is None:
        raise NotFound("Licence not found.")

    grant = await licence_service.grant_seat(
        session,
        tenant_id=principal.tenant_id,
        licence_id=uuid.UUID(licence_id),
        learner_user_id=uuid.UUID(body.learner_user_id),
        entitlement_id=uuid.UUID(body.entitlement_id) if body.entitlement_id else None,
    )

    return SeatGrantResponse(
        id=str(grant.id),
        licence_id=str(grant.licence_id),
        learner_user_id=str(grant.learner_user_id),
        entitlement_id=str(grant.entitlement_id) if grant.entitlement_id else None,
        granted_at=grant.granted_at.isoformat(),
        revoked_at=grant.revoked_at.isoformat() if grant.revoked_at else None,
    )


@router.get(
    "/organisations/{organisation_id}/licences/seat-grants",
    response_model=ListSeatGrantsResponse,
    summary="List seat grants for a licensee organisation",
)
async def list_seat_grants(
    organisation_id: str,
    include_revoked: bool = False,
    principal: PrincipalDep = None,
    session: SessionDep = None,
) -> ListSeatGrantsResponse:
    """List all seat grants for a licensee organisation.

    Returns grants under all licences belonging to the organisation.
    Includes revoked grants if include_revoked=true.
    """
    principal.require(MANAGE_LICENCES)

    grants = await licence_service.list_licensee_seat_grants(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=uuid.UUID(organisation_id),
        include_revoked=include_revoked,
    )

    return ListSeatGrantsResponse(
        items=[
            SeatGrantResponse(
                id=str(g.id),
                licence_id=str(g.licence_id),
                learner_user_id=str(g.learner_user_id),
                entitlement_id=str(g.entitlement_id) if g.entitlement_id else None,
                granted_at=g.granted_at.isoformat(),
                revoked_at=g.revoked_at.isoformat() if g.revoked_at else None,
            )
            for g in grants
        ]
    )


__all__ = ["router"]
