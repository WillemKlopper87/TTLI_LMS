"""Organisations and seats (02 §4.5, REQ-TEN-02).

Creation is self-service (any authenticated user can start one and
becomes its first admin — there is no signup flow yet, so the realistic
actor already has an account). Everything else is gated on membership
or, for seat management and PII, specifically on being that
organisation's own admin (`require_admin`) or, for the progress report,
its admin or manager (REQ-TEN-03) — checked via `services/organisations.py`.
"""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy import select

from src.core.deps import CryptoDep, PrincipalDep, SessionDep
from src.core.errors import AppError, Forbidden, NotFound
from src.models.organisation import Organisation, OrganisationMember
from src.schemas.organisations import (
    AssignedSeatResponse,
    AssignedSeatsResponse,
    AssignSeatsRequest,
    AssignSeatsResponse,
    CreateOrganisationRequest,
    MemberResponse,
    MembersResponse,
    OrganisationResponse,
    SeatAssignmentResultResponse,
    SeatSummariesResponse,
    SeatSummaryResponse,
)
from src.schemas.reports import LearnerRowResponse, ProgressReportResponse
from src.services import organisations as organisations_service
from src.services import reports as reports_service

router = APIRouter(tags=["organisations"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


@router.post(
    "/organisations", response_model=OrganisationResponse, status_code=status.HTTP_201_CREATED
)
async def create_organisation(
    body: CreateOrganisationRequest, principal: PrincipalDep, session: SessionDep
) -> OrganisationResponse:
    organisation = await organisations_service.create_organisation(
        session, tenant_id=principal.tenant_id, name=body.name, creator_user_id=principal.user_id
    )
    return OrganisationResponse(id=str(organisation.id), name=organisation.name)


@router.get("/organisations", response_model=list[OrganisationResponse])
async def list_own_organisations(
    principal: PrincipalDep, session: SessionDep
) -> list[OrganisationResponse]:
    stmt = (
        select(Organisation)
        .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
        .where(OrganisationMember.user_id == principal.user_id)
    )
    organisations = (await session.execute(stmt)).scalars().all()
    return [OrganisationResponse(id=str(o.id), name=o.name) for o in organisations]


@router.get("/organisations/{organisation_id}", response_model=OrganisationResponse)
async def get_organisation(
    organisation_id: str, principal: PrincipalDep, session: SessionDep
) -> OrganisationResponse:
    organisation = await organisations_service.require_membership(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=_parse_uuid(organisation_id),
        user_id=principal.user_id,
    )
    return OrganisationResponse(id=str(organisation.id), name=organisation.name)


@router.get("/organisations/{organisation_id}/members", response_model=MembersResponse)
async def list_members(
    organisation_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> MembersResponse:
    org_id = _parse_uuid(organisation_id)
    await organisations_service.require_membership(
        session, tenant_id=principal.tenant_id, organisation_id=org_id, user_id=principal.user_id
    )
    rows = await organisations_service.list_members(session, crypto, organisation_id=org_id)
    return MembersResponse(
        items=[
            MemberResponse(user_id=str(row.user_id), email=row.email, relationship=row.relationship)
            for row in rows
        ]
    )


@router.get("/organisations/{organisation_id}/seats", response_model=SeatSummariesResponse)
async def list_seats(
    organisation_id: str, principal: PrincipalDep, session: SessionDep
) -> SeatSummariesResponse:
    org_id = _parse_uuid(organisation_id)
    await organisations_service.require_membership(
        session, tenant_id=principal.tenant_id, organisation_id=org_id, user_id=principal.user_id
    )
    summaries = await organisations_service.list_seat_summaries(session, organisation_id=org_id)
    return SeatSummariesResponse(
        items=[
            SeatSummaryResponse(
                course_id=str(s.course_id),
                course_title=s.course_title,
                purchased=s.purchased,
                assigned=s.assigned,
                available=s.purchased - s.assigned,
            )
            for s in summaries
        ]
    )


@router.get(
    "/organisations/{organisation_id}/seats/{course_id}/assignments",
    response_model=AssignedSeatsResponse,
)
async def list_assigned_seats(
    organisation_id: str,
    course_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> AssignedSeatsResponse:
    org_id = _parse_uuid(organisation_id)
    await organisations_service.require_admin(
        session, tenant_id=principal.tenant_id, organisation_id=org_id, user_id=principal.user_id
    )
    rows = await organisations_service.list_assigned_seats(
        session, crypto, organisation_id=org_id, course_id=_parse_uuid(course_id)
    )
    return AssignedSeatsResponse(
        items=[
            AssignedSeatResponse(
                entitlement_id=str(row.entitlement_id),
                user_id=str(row.user_id),
                email=row.email,
                granted_at=row.granted_at.isoformat(),
            )
            for row in rows
        ]
    )


@router.get(
    "/organisations/{organisation_id}/reports/progress", response_model=ProgressReportResponse
)
async def progress_report(
    organisation_id: str,
    course_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> ProgressReportResponse:
    """REQ-TEN-03's report: response shape is determined by policy, not
    by query parameters. A caller who holds the relationship this route
    requires but fails any of the three individual-visibility conditions
    still gets the participation list — with every score withheld
    (`score_hidden: true`, `best_quiz_score: null`) and both the email
    and `display_name` masked. See `services/reports.py`'s module
    docstring for why that line moved from "no rows at all" to "rows
    without scores".

    The route itself is gated tighter than plain membership, though: this
    is the same "manager or admin" relationship `_can_view_individual`
    already treats as privileged for individual visibility, not the
    ordinary `member` relationship a seat holder gets just by having a
    seat assigned to them (`services/organisations.py::assign_seat`) —
    reusing that concept rather than inventing a separate one, same as
    the assigned-seats endpoint above reserves real PII for `require_admin`.
    """
    org_id = _parse_uuid(organisation_id)
    await organisations_service.require_membership(
        session, tenant_id=principal.tenant_id, organisation_id=org_id, user_id=principal.user_id
    )
    relationship = await organisations_service.get_relationship(
        session, organisation_id=org_id, user_id=principal.user_id
    )
    if relationship not in ("manager", "admin"):
        raise Forbidden("Only an organisation manager or admin can view this report.")
    report = await reports_service.get_progress_report(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        principal=principal,
        organisation_id=org_id,
        course_id=_parse_uuid(course_id),
    )
    return ProgressReportResponse(
        course_id=str(report.course_id),
        course_title=report.course_title,
        enrolled=report.enrolled,
        completed=report.completed,
        completion_rate=report.completion_rate,
        average_progress=report.average_progress,
        at_risk=report.at_risk,
        individual_visible=report.individual_visible,
        learners=[
            LearnerRowResponse(
                user_id=str(row.user_id),
                email=row.email,
                display_name=row.display_name,
                status=row.status,
                progress_percent=row.progress_percent,
                last_active_at=row.last_active_at,
                completed_at=row.completed_at,
                best_quiz_score=row.best_quiz_score,
                score_hidden=row.score_hidden,
            )
            for row in report.learners
        ],
    )


@router.post("/organisations/{organisation_id}/seats/invite", response_model=AssignSeatsResponse)
async def invite_members(
    organisation_id: str,
    body: AssignSeatsRequest,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> AssignSeatsResponse:
    org_id = _parse_uuid(organisation_id)
    await organisations_service.require_admin(
        session, tenant_id=principal.tenant_id, organisation_id=org_id, user_id=principal.user_id
    )
    results = await organisations_service.assign_seats_bulk(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        organisation_id=org_id,
        course_id=_parse_uuid(body.course_id),
        emails=body.emails,
    )
    return AssignSeatsResponse(
        items=[
            SeatAssignmentResultResponse(email=r.email, ok=r.ok, reason=r.reason) for r in results
        ]
    )


@router.post("/organisations/{organisation_id}/seats/import", response_model=AssignSeatsResponse)
async def import_members_csv(
    organisation_id: str,
    course_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    file: UploadFile = File(...),
) -> AssignSeatsResponse:
    """CSV import — REQ-TEN-02's second bulk-invite path. Expects one
    email address per row (a header row, if present, is skipped:
    anything that doesn't parse as an email-shaped string is dropped
    rather than crashing the whole import)."""
    org_id = _parse_uuid(organisation_id)
    await organisations_service.require_admin(
        session, tenant_id=principal.tenant_id, organisation_id=org_id, user_id=principal.user_id
    )
    data = await file.read()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("That file is not readable as UTF-8 text.") from exc

    emails: list[str] = []
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        candidate = row[0].strip()
        if "@" in candidate and candidate.lower() != "email":
            emails.append(candidate)

    if not emails:
        raise AppError("No email addresses found in that file.")

    results = await organisations_service.assign_seats_bulk(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        organisation_id=org_id,
        course_id=_parse_uuid(course_id),
        emails=emails,
    )
    return AssignSeatsResponse(
        items=[
            SeatAssignmentResultResponse(email=r.email, ok=r.ok, reason=r.reason) for r in results
        ]
    )


@router.post(
    "/organisations/{organisation_id}/seats/{entitlement_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def revoke_seat(
    organisation_id: str, entitlement_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    org_id = _parse_uuid(organisation_id)
    await organisations_service.require_admin(
        session, tenant_id=principal.tenant_id, organisation_id=org_id, user_id=principal.user_id
    )
    await organisations_service.revoke_seat(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=org_id,
        entitlement_id=_parse_uuid(entitlement_id),
    )


__all__ = ["router"]
