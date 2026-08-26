"""Workshops, facilitators, booking (02 §9, REQ-WS-01 through REQ-WS-09).

Creating facilitators/workshops/sessions is `workshop:manage` — an admin
action. Booking a session is self-service, like enrolling in a course —
any authenticated user may attempt it, gated on capacity rather than a
permission. Marking attendance and viewing a session's roster are gated
on being that session's own facilitator, or holding `workshop:manage`
(the same ownership-or-override pattern `routers/orders.py` uses for
finance).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from src.core.deps import CryptoDep, Principal, PrincipalDep, SessionDep, SettingsDep, TenantDep
from src.core.errors import AppError, Forbidden, NotFound
from src.models.user import User
from src.models.workshop import Booking, Facilitator, MeetingLink, Workshop, WorkshopSession
from src.schemas.workshops import (
    AddAvailabilityRequest,
    AddSessionFacilitatorRequest,
    AvailabilityPage,
    AvailabilityWindowResponse,
    BookingResponse,
    CancelSessionRequest,
    CreateFacilitatorRequest,
    CreateSessionRequest,
    CreateWorkshopRequest,
    FacilitatorResponse,
    FacilitatorsPage,
    MarkAttendanceRequest,
    OwnBookingResponse,
    OwnBookingsPage,
    PublicSessionRow,
    PublicWorkshopsResponse,
    RescheduleBookingRequest,
    RosterResponse,
    RosterRowResponse,
    SessionResponse,
    SessionsPage,
    UpdateWorkshopRequest,
    WorkshopResponse,
    WorkshopsPage,
)
from src.services import identity
from src.services import workshops as workshops_service
from src.services.ics import IcsEvent, build_ics
from src.services.meeting.teams import TeamsMeetingProvider
from src.services.meeting.zoom import ZoomMeetingProvider

router = APIRouter(tags=["workshops"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


async def _own_facilitator_or_manage(
    session: SessionDep, principal: Principal, facilitator_id: uuid.UUID
) -> None:
    if "workshop:manage" in principal.permissions:
        return
    facilitator = await session.get(Facilitator, facilitator_id)
    if facilitator is None or facilitator.user_id != principal.user_id:
        raise Forbidden("You do not have access to this facilitator.")


@router.post(
    "/facilitators", response_model=FacilitatorResponse, status_code=status.HTTP_201_CREATED
)
async def create_facilitator(
    body: CreateFacilitatorRequest, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> FacilitatorResponse:
    principal.require("workshop:manage")
    user = await identity.find_by_email(session, crypto, body.email)
    if user is None:
        raise AppError("No user with that email exists yet.")
    facilitator = await workshops_service.create_facilitator(
        session, tenant_id=principal.tenant_id, user_id=user.id, bio=body.bio
    )
    return FacilitatorResponse(
        id=str(facilitator.id),
        user_id=str(user.id),
        email=body.email,
        bio=facilitator.bio,
        timezone=facilitator.timezone,
    )


@router.get("/facilitators", response_model=FacilitatorsPage)
async def list_facilitators(
    principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> FacilitatorsPage:
    rows = await workshops_service.list_facilitators(session, crypto)
    return FacilitatorsPage(
        items=[
            FacilitatorResponse(
                id=str(r.id), user_id=str(r.user_id), email=r.email, bio=r.bio, timezone=r.timezone
            )
            for r in rows
        ]
    )


@router.post(
    "/facilitators/{facilitator_id}/availability",
    response_model=AvailabilityWindowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_availability(
    facilitator_id: str, body: AddAvailabilityRequest, principal: PrincipalDep, session: SessionDep
) -> AvailabilityWindowResponse:
    fid = _parse_uuid(facilitator_id)
    await _own_facilitator_or_manage(session, principal, fid)
    window = await workshops_service.add_availability(
        session,
        tenant_id=principal.tenant_id,
        facilitator_id=fid,
        day_of_week=body.day_of_week,
        start_time_str=body.start_time,
        end_time_str=body.end_time,
    )
    return AvailabilityWindowResponse(
        id=str(window.id),
        day_of_week=window.day_of_week,
        start_time=window.start_time.isoformat(timespec="minutes"),
        end_time=window.end_time.isoformat(timespec="minutes"),
    )


@router.get("/facilitators/{facilitator_id}/availability", response_model=AvailabilityPage)
async def list_availability(
    facilitator_id: str, principal: PrincipalDep, session: SessionDep
) -> AvailabilityPage:
    windows = await workshops_service.list_availability(
        session, facilitator_id=_parse_uuid(facilitator_id)
    )
    return AvailabilityPage(
        items=[
            AvailabilityWindowResponse(
                id=str(w.id),
                day_of_week=w.day_of_week,
                start_time=w.start_time.isoformat(timespec="minutes"),
                end_time=w.end_time.isoformat(timespec="minutes"),
            )
            for w in windows
        ]
    )


def _workshop_response(workshop: Workshop) -> WorkshopResponse:
    return WorkshopResponse(
        id=str(workshop.id),
        title=workshop.title,
        description=workshop.description,
        session_type=workshop.session_type,
        default_duration_minutes=workshop.default_duration_minutes,
        requires_credit=workshop.requires_credit,
        meeting_provider=workshop.meeting_provider,
    )


@router.post("/workshops", response_model=WorkshopResponse, status_code=status.HTTP_201_CREATED)
async def create_workshop(
    body: CreateWorkshopRequest, principal: PrincipalDep, session: SessionDep
) -> WorkshopResponse:
    principal.require("workshop:manage")
    workshop = await workshops_service.create_workshop(
        session,
        tenant_id=principal.tenant_id,
        title=body.title,
        description=body.description,
        session_type=body.session_type,
        default_duration_minutes=body.default_duration_minutes,
    )
    return _workshop_response(workshop)


@router.get("/workshops", response_model=WorkshopsPage)
async def list_workshops(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> WorkshopsPage:
    workshops = await workshops_service.list_workshops(session, tenant_id=principal.tenant_id)
    return WorkshopsPage(
        items=[_workshop_response(w) for w in workshops],
        teams_configured=TeamsMeetingProvider(settings).is_configured(),
        zoom_configured=ZoomMeetingProvider(settings).is_configured(),
    )


@router.patch("/workshops/{workshop_id}", response_model=WorkshopResponse)
async def update_workshop(
    workshop_id: str, body: UpdateWorkshopRequest, principal: PrincipalDep, session: SessionDep
) -> WorkshopResponse:
    principal.require("workshop:manage")
    workshop = await workshops_service.update_workshop(
        session,
        tenant_id=principal.tenant_id,
        workshop_id=_parse_uuid(workshop_id),
        requires_credit=body.requires_credit,
        meeting_provider=body.meeting_provider,
    )
    return _workshop_response(workshop)


async def _session_response(
    session: SessionDep, workshop_session: WorkshopSession
) -> SessionResponse:
    registered, waitlisted = await workshops_service.seat_counts(
        session, session_id=workshop_session.id
    )
    return SessionResponse(
        id=str(workshop_session.id),
        workshop_id=str(workshop_session.workshop_id),
        facilitator_id=str(workshop_session.facilitator_id),
        starts_at=workshop_session.starts_at,
        ends_at=workshop_session.ends_at,
        capacity=workshop_session.capacity,
        status=workshop_session.status,
        registered=registered,
        waitlisted=waitlisted,
    )


@router.post(
    "/workshops/{workshop_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    workshop_id: str, body: CreateSessionRequest, principal: PrincipalDep, session: SessionDep
) -> SessionResponse:
    principal.require("workshop:manage")
    workshop_session = await workshops_service.create_session(
        session,
        tenant_id=principal.tenant_id,
        workshop_id=_parse_uuid(workshop_id),
        facilitator_id=_parse_uuid(body.facilitator_id),
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        capacity=body.capacity,
    )
    return await _session_response(session, workshop_session)


@router.get("/workshops/{workshop_id}/sessions", response_model=SessionsPage)
async def list_sessions(
    workshop_id: str, principal: PrincipalDep, session: SessionDep
) -> SessionsPage:
    sessions = await workshops_service.list_sessions(
        session, tenant_id=principal.tenant_id, workshop_id=_parse_uuid(workshop_id)
    )
    return SessionsPage(items=[await _session_response(session, s) for s in sessions])


@router.post("/sessions/{session_id}/cancel", response_model=SessionResponse)
async def cancel_session(
    session_id: str,
    body: CancelSessionRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> SessionResponse:
    sid = _parse_uuid(session_id)
    await _require_session_facilitator_or_manage(session, principal, sid)
    workshop_session = await workshops_service.cancel_session(
        session,
        settings,
        tenant_id=principal.tenant_id,
        session_id=sid,
        actor_user_id=principal.user_id,
        reason=body.reason,
    )
    return await _session_response(session, workshop_session)


@router.get("/sessions/{session_id}/facilitators", response_model=FacilitatorsPage)
async def list_session_facilitators(
    session_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> FacilitatorsPage:
    rows = await workshops_service.list_session_facilitators(
        session, crypto, session_id=_parse_uuid(session_id)
    )
    return FacilitatorsPage(
        items=[
            FacilitatorResponse(
                id=str(r.id), user_id=str(r.user_id), email=r.email, bio=r.bio, timezone=r.timezone
            )
            for r in rows
        ]
    )


@router.post(
    "/sessions/{session_id}/facilitators",
    response_model=FacilitatorsPage,
    status_code=status.HTTP_201_CREATED,
)
async def add_session_facilitator(
    session_id: str,
    body: AddSessionFacilitatorRequest,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> FacilitatorsPage:
    principal.require("workshop:manage")
    sid = _parse_uuid(session_id)
    await workshops_service.add_session_facilitator(
        session,
        tenant_id=principal.tenant_id,
        session_id=sid,
        facilitator_id=_parse_uuid(body.facilitator_id),
    )
    rows = await workshops_service.list_session_facilitators(session, crypto, session_id=sid)
    return FacilitatorsPage(
        items=[
            FacilitatorResponse(
                id=str(r.id), user_id=str(r.user_id), email=r.email, bio=r.bio, timezone=r.timezone
            )
            for r in rows
        ]
    )


@router.delete(
    "/sessions/{session_id}/facilitators/{facilitator_id}",
    response_model=FacilitatorsPage,
)
async def remove_session_facilitator(
    session_id: str,
    facilitator_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> FacilitatorsPage:
    principal.require("workshop:manage")
    sid = _parse_uuid(session_id)
    await workshops_service.remove_session_facilitator(
        session,
        tenant_id=principal.tenant_id,
        session_id=sid,
        facilitator_id=_parse_uuid(facilitator_id),
    )
    rows = await workshops_service.list_session_facilitators(session, crypto, session_id=sid)
    return FacilitatorsPage(
        items=[
            FacilitatorResponse(
                id=str(r.id), user_id=str(r.user_id), email=r.email, bio=r.bio, timezone=r.timezone
            )
            for r in rows
        ]
    )


@router.post("/sessions/{session_id}/book", response_model=BookingResponse)
async def book_session(
    session_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
) -> BookingResponse:
    booking = await workshops_service.book_session(
        session,
        crypto,
        settings,
        tenant_id=principal.tenant_id,
        session_id=_parse_uuid(session_id),
        user_id=principal.user_id,
    )
    link = (
        await session.execute(
            select(MeetingLink).where(MeetingLink.session_id == booking.session_id)
        )
    ).scalar_one_or_none()
    return BookingResponse(
        id=str(booking.id),
        session_id=str(booking.session_id),
        user_id=str(booking.user_id),
        status=booking.status,
        join_url=link.join_url if link else None,
    )


@router.post(
    "/bookings/{booking_id}/cancel", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def cancel_booking(
    booking_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
) -> None:
    await workshops_service.cancel_booking(
        session,
        crypto,
        settings,
        tenant_id=principal.tenant_id,
        booking_id=_parse_uuid(booking_id),
        actor_user_id=principal.user_id,
    )


@router.post("/bookings/{booking_id}/reschedule", response_model=BookingResponse)
async def reschedule_booking(
    booking_id: str,
    body: RescheduleBookingRequest,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
) -> BookingResponse:
    booking = await workshops_service.reschedule_booking(
        session,
        crypto,
        settings,
        tenant_id=principal.tenant_id,
        booking_id=_parse_uuid(booking_id),
        target_session_id=_parse_uuid(body.target_session_id),
        actor_user_id=principal.user_id,
    )
    link = (
        await session.execute(
            select(MeetingLink).where(MeetingLink.session_id == booking.session_id)
        )
    ).scalar_one_or_none()
    return BookingResponse(
        id=str(booking.id),
        session_id=str(booking.session_id),
        user_id=str(booking.user_id),
        status=booking.status,
        join_url=link.join_url if link else None,
    )


@router.get("/bookings", response_model=OwnBookingsPage)
async def list_own_bookings(
    principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> OwnBookingsPage:
    rows = await workshops_service.list_own_bookings(
        session, crypto, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    return OwnBookingsPage(
        items=[
            OwnBookingResponse(
                booking_id=str(r.booking_id),
                session_id=str(r.session_id),
                workshop_id=str(r.workshop_id),
                workshop_title=r.workshop_title,
                facilitator_names=r.facilitator_names,
                starts_at=r.starts_at,
                ends_at=r.ends_at,
                status=r.status,
                session_status=r.session_status,
                join_url=r.join_url,
                provider=r.provider,
                can_manage=r.can_manage,
            )
            for r in rows
        ]
    )


@router.get(
    "/bookings/{booking_id}/calendar.ics",
    summary="A downloadable calendar invite for one of the caller's own bookings",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
async def get_booking_calendar(
    booking_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> Response:
    ctx = await workshops_service.get_booking_ics_context(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        booking_id=_parse_uuid(booking_id),
        actor_user_id=principal.user_id,
    )
    organizer = ctx.facilitator_names[0] if ctx.facilitator_names else "no-reply@ttli.local"
    ics_bytes = build_ics(
        IcsEvent(
            uid=ctx.booking.id,
            summary=ctx.workshop.title,
            description=ctx.workshop.description,
            location=None,
            starts_at=ctx.workshop_session.starts_at,
            ends_at=ctx.workshop_session.ends_at,
            organizer_email=organizer,
            status="CANCELLED" if ctx.booking.status == "cancelled" else "CONFIRMED",
        ),
        now=datetime.now(UTC),
    )
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="session.ics"'},
    )


async def _require_session_facilitator_or_manage(
    session: SessionDep, principal: Principal, session_id: uuid.UUID
) -> WorkshopSession:
    workshop_session = await session.get(WorkshopSession, session_id)
    if workshop_session is None or workshop_session.tenant_id != principal.tenant_id:
        raise NotFound("No such session.")
    if "workshop:manage" not in principal.permissions:
        facilitator = await session.get(Facilitator, workshop_session.facilitator_id)
        if facilitator is None or facilitator.user_id != principal.user_id:
            raise Forbidden("You do not have access to this session.")
    return workshop_session


@router.post("/sessions/{session_id}/attendance", response_model=RosterRowResponse)
async def mark_attendance(
    session_id: str,
    body: MarkAttendanceRequest,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> RosterRowResponse:
    sid = _parse_uuid(session_id)
    await _require_session_facilitator_or_manage(session, principal, sid)
    record = await workshops_service.mark_attendance(
        session,
        tenant_id=principal.tenant_id,
        session_id=sid,
        user_id=_parse_uuid(body.user_id),
        status=body.status,
        recorded_by_user_id=principal.user_id,
    )
    booking = await session.get(Booking, record.booking_id)
    if booking is None:  # pragma: no cover - mark_attendance always resolves a real booking
        raise NotFound("No such booking.")
    user = await session.get(User, booking.user_id)
    if user is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such user.")
    return RosterRowResponse(
        booking_id=str(record.booking_id),
        user_id=str(booking.user_id),
        email=crypto.decrypt(user.email_encrypted),
        booking_status=booking.status,
        attendance_status=record.status,
    )


@router.get("/sessions/{session_id}/roster", response_model=RosterResponse)
async def list_roster(
    session_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> RosterResponse:
    sid = _parse_uuid(session_id)
    await _require_session_facilitator_or_manage(session, principal, sid)
    rows = await workshops_service.list_roster(session, crypto, session_id=sid)
    return RosterResponse(
        items=[
            RosterRowResponse(
                booking_id=str(r.booking_id),
                user_id=str(r.user_id),
                email=r.email,
                booking_status=r.booking_status,
                attendance_status=r.attendance_status,
            )
            for r in rows
        ]
    )


@router.get(
    "/public/workshops",
    response_model=PublicWorkshopsResponse,
    summary="Upcoming bookable sessions, no auth required",
)
async def list_public_workshops(
    session: SessionDep, tenant: TenantDep, crypto: CryptoDep
) -> PublicWorkshopsResponse:
    """The public face of the workshop subsystem (REQ-WS-*), which until
    now was only reachable through the admin screens. Shows what a
    visitor needs to decide whether to attend — when, who leads it, and
    whether seats remain — and nothing that belongs to an attendee: no
    join link, no roster, no attendance.
    """
    rows = await workshops_service.list_public_sessions(session, tenant_id=tenant.id)
    items: list[PublicSessionRow] = []
    for workshop_session, workshop, user, registered in rows:
        # Facilitators are public-facing, but the name is encrypted at
        # rest like every other; decrypt only this one field, and only
        # when it exists.
        name: str | None = None
        if user is not None and user.full_name_encrypted is not None:
            name = crypto.decrypt(user.full_name_encrypted)
        seats_left = max(0, workshop_session.capacity - registered)
        duration = int(
            (workshop_session.ends_at - workshop_session.starts_at).total_seconds() // 60
        )
        items.append(
            PublicSessionRow(
                session_id=str(workshop_session.id),
                workshop_id=str(workshop.id),
                title=workshop.title,
                description=workshop.description,
                session_type=workshop.session_type,
                facilitator_name=name,
                starts_at=workshop_session.starts_at,
                ends_at=workshop_session.ends_at,
                duration_minutes=duration,
                capacity=workshop_session.capacity,
                seats_left=seats_left,
                is_full=seats_left == 0,
            )
        )
    return PublicWorkshopsResponse(items=items)


__all__ = ["router"]
