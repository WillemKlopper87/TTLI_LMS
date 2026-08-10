"""Workshops, facilitators, booking (02 §9, REQ-WS-01 through REQ-WS-09).
See `0018`'s migration docstring for what this sprint deliberately
deferred and why.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.crypto import CryptoBox
from src.core.errors import AppError, Forbidden, NotFound
from src.core.ids import uuid7
from src.models.user import User
from src.models.workshop import (
    ATTENDANCE_STATUS_VALUES,
    AttendanceRecord,
    Booking,
    Facilitator,
    FacilitatorAvailability,
    MeetingLink,
    Workshop,
    WorkshopSession,
)
from src.services import meeting as meeting_service


class WorkshopError(AppError):
    """A refusal in the booking flow — full session, already booked,
    outside availability, or a state transition that doesn't apply."""

    code = "WORKSHOP_ERROR"


async def create_facilitator(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, bio: str | None
) -> Facilitator:
    existing = (
        await session.execute(
            select(Facilitator).where(
                Facilitator.tenant_id == tenant_id, Facilitator.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise WorkshopError("This user is already a facilitator.")
    facilitator = Facilitator(id=uuid7(), tenant_id=tenant_id, user_id=user_id, bio=bio)
    session.add(facilitator)
    await session.flush()
    return facilitator


@dataclass(frozen=True, slots=True)
class FacilitatorRow:
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    bio: str | None
    timezone: str


async def list_facilitators(session: AsyncSession, crypto: CryptoBox) -> list[FacilitatorRow]:
    stmt = select(Facilitator, User).join(User, User.id == Facilitator.user_id)
    rows = (await session.execute(stmt)).all()
    return [
        FacilitatorRow(
            id=f.id,
            user_id=f.user_id,
            email=crypto.decrypt(u.email_encrypted),
            bio=f.bio,
            timezone=f.timezone,
        )
        for f, u in rows
    ]


async def add_availability(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    facilitator_id: uuid.UUID,
    day_of_week: int,
    start_time_str: str,
    end_time_str: str,
) -> FacilitatorAvailability:
    try:
        start = time.fromisoformat(start_time_str)
        end = time.fromisoformat(end_time_str)
    except ValueError as exc:
        raise WorkshopError("Times must be HH:MM.") from exc
    if end <= start:
        raise WorkshopError("End time must be after start time.")
    if not 0 <= day_of_week <= 6:
        raise WorkshopError("day_of_week must be between 0 (Monday) and 6 (Sunday).")

    window = FacilitatorAvailability(
        id=uuid7(),
        tenant_id=tenant_id,
        facilitator_id=facilitator_id,
        day_of_week=day_of_week,
        start_time=start,
        end_time=end,
    )
    session.add(window)
    await session.flush()
    return window


async def list_availability(
    session: AsyncSession, *, facilitator_id: uuid.UUID
) -> list[FacilitatorAvailability]:
    stmt = (
        select(FacilitatorAvailability)
        .where(FacilitatorAvailability.facilitator_id == facilitator_id)
        .order_by(FacilitatorAvailability.day_of_week, FacilitatorAvailability.start_time)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_workshop(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    description: str | None,
    session_type: str,
    default_duration_minutes: int,
) -> Workshop:
    workshop = Workshop(
        id=uuid7(),
        tenant_id=tenant_id,
        title=title,
        description=description,
        session_type=session_type,
        default_duration_minutes=default_duration_minutes,
    )
    session.add(workshop)
    await session.flush()
    return workshop


async def list_workshops(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Workshop]:
    stmt = select(Workshop).where(Workshop.tenant_id == tenant_id).order_by(Workshop.title)
    return list((await session.execute(stmt)).scalars().all())


async def _facilitator_available_at(
    session: AsyncSession, *, facilitator_id: uuid.UUID, starts_at: datetime, ends_at: datetime
) -> bool:
    """REQ-WS-02: a session may only be scheduled inside one of the
    facilitator's own weekly availability windows. Compared in UTC —
    `facilitators.timezone` is display metadata for this sprint, not a
    conversion applied here (documented, same scope boundary as
    the credit-based-booking deferral)."""
    windows = await list_availability(session, facilitator_id=facilitator_id)
    if not windows:
        return False
    day = starts_at.weekday()
    start_t, end_t = starts_at.time(), ends_at.time()
    return any(
        w.day_of_week == day and w.start_time <= start_t and end_t <= w.end_time for w in windows
    )


async def _facilitator_has_conflict(
    session: AsyncSession, *, facilitator_id: uuid.UUID, starts_at: datetime, ends_at: datetime
) -> bool:
    stmt = select(WorkshopSession).where(
        WorkshopSession.facilitator_id == facilitator_id,
        WorkshopSession.status == "scheduled",
        WorkshopSession.starts_at < ends_at,
        WorkshopSession.ends_at > starts_at,
    )
    return (await session.execute(stmt)).scalars().first() is not None


async def create_session(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workshop_id: uuid.UUID,
    facilitator_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    capacity: int,
) -> WorkshopSession:
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.tenant_id != tenant_id:
        raise NotFound("No such workshop.")
    facilitator = await session.get(Facilitator, facilitator_id)
    if facilitator is None or facilitator.tenant_id != tenant_id:
        raise NotFound("No such facilitator.")
    if ends_at <= starts_at:
        raise WorkshopError("Session end must be after its start.")
    if capacity < 1:
        raise WorkshopError("Capacity must be at least 1.")
    if not await _facilitator_available_at(
        session, facilitator_id=facilitator_id, starts_at=starts_at, ends_at=ends_at
    ):
        raise WorkshopError("This falls outside the facilitator's stated availability.")
    if await _facilitator_has_conflict(
        session, facilitator_id=facilitator_id, starts_at=starts_at, ends_at=ends_at
    ):
        raise WorkshopError("The facilitator already has a session in this window.")

    workshop_session = WorkshopSession(
        id=uuid7(),
        tenant_id=tenant_id,
        workshop_id=workshop_id,
        facilitator_id=facilitator_id,
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=capacity,
    )
    session.add(workshop_session)
    await session.flush()
    return workshop_session


async def list_sessions(
    session: AsyncSession, *, tenant_id: uuid.UUID, workshop_id: uuid.UUID | None = None
) -> list[WorkshopSession]:
    stmt = select(WorkshopSession).where(WorkshopSession.tenant_id == tenant_id)
    if workshop_id is not None:
        stmt = stmt.where(WorkshopSession.workshop_id == workshop_id)
    stmt = stmt.order_by(WorkshopSession.starts_at)
    return list((await session.execute(stmt)).scalars().all())


async def seat_counts(session: AsyncSession, *, session_id: uuid.UUID) -> tuple[int, int]:
    """(registered, waitlisted) — active bookings only."""
    stmt = select(Booking.status).where(
        Booking.session_id == session_id, Booking.status != "cancelled"
    )
    statuses = (await session.execute(stmt)).scalars().all()
    return sum(1 for s in statuses if s == "registered"), sum(
        1 for s in statuses if s == "waitlisted"
    )


async def book_session(
    session: AsyncSession,
    crypto: CryptoBox,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Booking:
    workshop_session = await session.get(WorkshopSession, session_id)
    if workshop_session is None or workshop_session.tenant_id != tenant_id:
        raise NotFound("No such session.")
    if workshop_session.status != "scheduled":
        raise WorkshopError("This session is no longer taking bookings.")

    existing = (
        await session.execute(
            select(Booking).where(Booking.session_id == session_id, Booking.user_id == user_id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status != "cancelled":
        raise WorkshopError("You already have a booking for this session.")

    registered, _ = await seat_counts(session, session_id=session_id)
    status = "registered" if registered < workshop_session.capacity else "waitlisted"

    if existing is not None:
        existing.status = status
        booking = existing
    else:
        booking = Booking(
            id=uuid7(), tenant_id=tenant_id, session_id=session_id, user_id=user_id, status=status
        )
        session.add(booking)
    await session.flush()

    session.add(
        AttendanceRecord(
            id=uuid7(),
            tenant_id=tenant_id,
            booking_id=booking.id,
            status="registered",
            source="facilitator_manual",
        )
    )

    if status == "registered":
        link = (
            await session.execute(select(MeetingLink).where(MeetingLink.session_id == session_id))
        ).scalar_one_or_none()
        if link is None:
            provider = meeting_service.get_provider("manual", settings=settings)
            details = await provider.create_meeting(
                session=workshop_session, organiser_user_id=workshop_session.facilitator_id
            )
            session.add(
                MeetingLink(
                    id=uuid7(),
                    tenant_id=tenant_id,
                    session_id=session_id,
                    provider=details.provider,
                    provider_meeting_id=details.provider_meeting_id,
                    join_url=details.join_url,
                    organiser_user_id=user_id,
                )
            )

    await session.flush()
    return booking


async def cancel_booking(
    session: AsyncSession, *, tenant_id: uuid.UUID, booking_id: uuid.UUID, actor_user_id: uuid.UUID
) -> None:
    booking = await session.get(Booking, booking_id)
    if booking is None or booking.tenant_id != tenant_id:
        raise NotFound("No such booking.")
    if booking.status == "cancelled":
        raise WorkshopError("This booking is already cancelled.")

    workshop_session = await session.get(WorkshopSession, booking.session_id)
    if workshop_session is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such session.")
    facilitator = await session.get(Facilitator, workshop_session.facilitator_id)
    is_facilitator = facilitator is not None and facilitator.user_id == actor_user_id
    if booking.user_id != actor_user_id and not is_facilitator:
        raise Forbidden("You do not have access to this booking.")

    was_registered = booking.status == "registered"
    booking.status = "cancelled"

    record = (
        await session.execute(
            select(AttendanceRecord).where(AttendanceRecord.booking_id == booking.id)
        )
    ).scalar_one_or_none()
    if record is not None:
        record.status = "cancelled"

    if was_registered:
        # REQ-WS-03's waitlist: the earliest still-waitlisted booking
        # takes the seat that just freed up.
        next_in_line = (
            (
                await session.execute(
                    select(Booking)
                    .where(Booking.session_id == booking.session_id, Booking.status == "waitlisted")
                    .order_by(Booking.created_at)
                )
            )
            .scalars()
            .first()
        )
        if next_in_line is not None:
            next_in_line.status = "registered"
            promoted_record = (
                await session.execute(
                    select(AttendanceRecord).where(AttendanceRecord.booking_id == next_in_line.id)
                )
            ).scalar_one_or_none()
            if promoted_record is not None:
                promoted_record.status = "registered"

    await session.flush()


async def mark_attendance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str,
    recorded_by_user_id: uuid.UUID,
) -> AttendanceRecord:
    if status not in ATTENDANCE_STATUS_VALUES:
        raise WorkshopError(f"Unknown attendance status: {status}")
    booking = (
        await session.execute(
            select(Booking).where(Booking.session_id == session_id, Booking.user_id == user_id)
        )
    ).scalar_one_or_none()
    if booking is None or booking.tenant_id != tenant_id:
        raise NotFound("No booking for this learner and session.")

    record = (
        await session.execute(
            select(AttendanceRecord).where(AttendanceRecord.booking_id == booking.id)
        )
    ).scalar_one_or_none()
    if record is None:  # pragma: no cover - booking always creates one
        raise NotFound("No attendance record for this booking.")

    record.status = status
    record.source = "facilitator_manual"
    record.recorded_by_user_id = recorded_by_user_id
    record.recorded_at = datetime.now(UTC)
    await session.flush()
    return record


@dataclass(frozen=True, slots=True)
class RosterRow:
    booking_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    booking_status: str
    attendance_status: str


async def list_roster(
    session: AsyncSession, crypto: CryptoBox, *, session_id: uuid.UUID
) -> list[RosterRow]:
    stmt = (
        select(Booking, User, AttendanceRecord)
        .join(User, User.id == Booking.user_id)
        .join(AttendanceRecord, AttendanceRecord.booking_id == Booking.id)
        .where(Booking.session_id == session_id)
        .order_by(Booking.created_at)
    )
    rows = (await session.execute(stmt)).all()
    return [
        RosterRow(
            booking_id=b.id,
            user_id=u.id,
            email=crypto.decrypt(u.email_encrypted),
            booking_status=b.status,
            attendance_status=a.status,
        )
        for b, u, a in rows
    ]


__all__ = [
    "FacilitatorRow",
    "RosterRow",
    "WorkshopError",
    "add_availability",
    "book_session",
    "cancel_booking",
    "create_facilitator",
    "create_session",
    "create_workshop",
    "list_availability",
    "list_facilitators",
    "list_roster",
    "list_sessions",
    "list_workshops",
    "mark_attendance",
    "seat_counts",
]
