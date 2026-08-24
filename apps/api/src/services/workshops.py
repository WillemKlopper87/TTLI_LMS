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
from src.models.audit import AuditAction
from src.models.user import User
from src.models.workshop import (
    ATTENDANCE_STATUS_VALUES,
    AttendanceRecord,
    Booking,
    Facilitator,
    FacilitatorAvailability,
    MeetingLink,
    SessionFacilitator,
    Workshop,
    WorkshopSession,
)
from src.services import audit, push
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
    """Checked via `session_facilitators`, not `WorkshopSession.
    facilitator_id` directly (P7) — every session's primary facilitator
    is always also a `session_facilitators` row (`create_session`/
    `0036`'s backfill both guarantee it), so this one join catches a
    conflict whether the facilitator is primary on the other session or
    only a co-facilitator on it. Checking `facilitator_id` alone would
    silently miss the co-facilitator case — exactly the gap multi-
    facilitator support needs closed."""
    stmt = (
        select(WorkshopSession)
        .join(SessionFacilitator, SessionFacilitator.session_id == WorkshopSession.id)
        .where(
            SessionFacilitator.facilitator_id == facilitator_id,
            WorkshopSession.status == "scheduled",
            WorkshopSession.starts_at < ends_at,
            WorkshopSession.ends_at > starts_at,
        )
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
    # The primary facilitator is always a session_facilitators row too
    # (P7) — every existing session got this via 0036's backfill; a
    # session created after that migration needs the same invariant
    # held here, or "every facilitator on this session" would silently
    # miss the primary the moment it's queried through this table alone.
    session.add(
        SessionFacilitator(
            id=uuid7(),
            tenant_id=tenant_id,
            session_id=workshop_session.id,
            facilitator_id=facilitator_id,
        )
    )
    await session.flush()
    return workshop_session


async def add_session_facilitator(
    session: AsyncSession, *, tenant_id: uuid.UUID, session_id: uuid.UUID, facilitator_id: uuid.UUID
) -> SessionFacilitator:
    """A co-facilitator, checked against their *own* availability and
    conflicts (P7, REQ-WS-02/03) — the exact gap the single-`facilitator_
    id` design left open: nothing ever checked a co-facilitator's own
    schedule, because there was no way to add one at all."""
    workshop_session = await session.get(WorkshopSession, session_id)
    if workshop_session is None or workshop_session.tenant_id != tenant_id:
        raise NotFound("No such session.")
    facilitator = await session.get(Facilitator, facilitator_id)
    if facilitator is None or facilitator.tenant_id != tenant_id:
        raise NotFound("No such facilitator.")

    existing = (
        await session.execute(
            select(SessionFacilitator.id).where(
                SessionFacilitator.session_id == session_id,
                SessionFacilitator.facilitator_id == facilitator_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise WorkshopError("This facilitator is already on this session.")

    if not await _facilitator_available_at(
        session,
        facilitator_id=facilitator_id,
        starts_at=workshop_session.starts_at,
        ends_at=workshop_session.ends_at,
    ):
        raise WorkshopError("This falls outside the facilitator's stated availability.")
    if await _facilitator_has_conflict(
        session,
        facilitator_id=facilitator_id,
        starts_at=workshop_session.starts_at,
        ends_at=workshop_session.ends_at,
    ):
        raise WorkshopError("The facilitator already has a session in this window.")

    link = SessionFacilitator(
        id=uuid7(), tenant_id=tenant_id, session_id=session_id, facilitator_id=facilitator_id
    )
    session.add(link)
    await session.flush()
    return link


async def remove_session_facilitator(
    session: AsyncSession, *, tenant_id: uuid.UUID, session_id: uuid.UUID, facilitator_id: uuid.UUID
) -> None:
    workshop_session = await session.get(WorkshopSession, session_id)
    if workshop_session is None or workshop_session.tenant_id != tenant_id:
        raise NotFound("No such session.")

    link = (
        await session.execute(
            select(SessionFacilitator).where(
                SessionFacilitator.session_id == session_id,
                SessionFacilitator.facilitator_id == facilitator_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFound("That facilitator is not on this session.")

    remaining = (
        (
            await session.execute(
                select(SessionFacilitator.id).where(SessionFacilitator.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    if len(remaining) <= 1:
        raise WorkshopError("A session must keep at least one facilitator.")

    if workshop_session.facilitator_id == facilitator_id:
        raise WorkshopError(
            "Can't remove the primary facilitator — add a replacement, then reassign it first."
        )

    await session.delete(link)
    await session.flush()


async def list_session_facilitators(
    session: AsyncSession, crypto: CryptoBox, *, session_id: uuid.UUID
) -> list[FacilitatorRow]:
    stmt = (
        select(Facilitator, User)
        .join(SessionFacilitator, SessionFacilitator.facilitator_id == Facilitator.id)
        .join(User, User.id == Facilitator.user_id)
        .where(SessionFacilitator.session_id == session_id)
    )
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


async def cancel_session(
    session: AsyncSession,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> WorkshopSession:
    """Cancels the whole session, not one booking (P7, REQ-WS-03) — the
    gap this codebase had zero code path for until now. Cancels every
    active booking, refunds a consumed credit for each (Phase 4 wires
    that half in; harmless no-op until then since consumed_entitlement_id
    is always null before it), cancels the provider meeting, and tells
    every affected registrant.

    `actor_user_id` is trusted, not re-checked here — the router calls
    `_require_session_facilitator_or_manage` first, the same
    this-session's-own-facilitator-or-workshop:manage gate
    `mark_attendance`/`list_roster` already use."""
    workshop_session = await session.get(WorkshopSession, session_id)
    if workshop_session is None or workshop_session.tenant_id != tenant_id:
        raise NotFound("No such session.")
    if workshop_session.status == "cancelled":
        raise WorkshopError("This session is already cancelled.")

    workshop_session.status = "cancelled"

    bookings = (
        (
            await session.execute(
                select(Booking).where(
                    Booking.session_id == session_id, Booking.status != "cancelled"
                )
            )
        )
        .scalars()
        .all()
    )
    for booking in bookings:
        await _cancel_booking_row(session, booking=booking, resulting_status="cancelled")
        await push.notify_user(
            session,
            tenant_id=tenant_id,
            user_id=booking.user_id,
            title="A session you booked was cancelled",
            body=reason or "The facilitator or an admin cancelled this session.",
        )

    link = (
        await session.execute(select(MeetingLink).where(MeetingLink.session_id == session_id))
    ).scalar_one_or_none()
    if link is not None:
        provider = meeting_service.get_provider(link.provider, settings=settings)
        await provider.cancel_meeting(provider_meeting_id=link.provider_meeting_id)

    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.WORKSHOP_SESSION_CANCELLED,
        actor_user_id=actor_user_id,
        entity_type="workshop_session",
        entity_id=workshop_session.id,
        after={"status": "cancelled", "reason": reason},
    )
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


async def list_public_sessions(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 12
) -> list[tuple[WorkshopSession, Workshop, User | None, int]]:
    """Upcoming, scheduled sessions for the public workshops page, with
    their seat counts. Only `scheduled` sessions starting in the future
    are returned — a cancelled or finished session is not something a
    visitor can book, and showing it would be an invitation to try."""
    # The facilitator's name lives on the encrypted User record, so the
    # caller decrypts it — a facilitator is public-facing by design (they
    # lead the session), but the decryption stays an explicit choice at
    # the boundary rather than something this query leaks by default.
    stmt = (
        select(WorkshopSession, Workshop, User)
        .join(Workshop, Workshop.id == WorkshopSession.workshop_id)
        .outerjoin(Facilitator, Facilitator.id == WorkshopSession.facilitator_id)
        .outerjoin(User, User.id == Facilitator.user_id)
        .where(
            WorkshopSession.tenant_id == tenant_id,
            WorkshopSession.status == "scheduled",
            WorkshopSession.starts_at > datetime.now(UTC),
        )
        .order_by(WorkshopSession.starts_at)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    out: list[tuple[WorkshopSession, Workshop, User | None, int]] = []
    for workshop_session, workshop, user in rows:
        registered, _ = await seat_counts(session, session_id=workshop_session.id)
        out.append((workshop_session, workshop, user, registered))
    return out


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


async def _cancel_booking_row(
    session: AsyncSession, *, booking: Booking, resulting_status: str = "cancelled"
) -> None:
    """The actual state transition, shared by `cancel_booking` (one
    booking, permission-checked) and `cancel_session` (every booking on
    a session, already permission-checked once by its caller) — same
    waitlist-promotion and attendance-record bookkeeping either way.
    `resulting_status` is `"cancelled"` normally, `"rescheduled"` when
    called from `reschedule_booking` (Phase 2) — the `attendance_status`
    enum has carried that value, unused, since `0018`."""
    was_registered = booking.status == "registered"
    booking.status = "cancelled"

    record = (
        await session.execute(
            select(AttendanceRecord).where(AttendanceRecord.booking_id == booking.id)
        )
    ).scalar_one_or_none()
    if record is not None:
        record.status = resulting_status

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

    await _cancel_booking_row(session, booking=booking, resulting_status="cancelled")


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
    "add_session_facilitator",
    "book_session",
    "cancel_booking",
    "cancel_session",
    "create_facilitator",
    "create_session",
    "create_workshop",
    "list_availability",
    "list_facilitators",
    "list_public_sessions",
    "list_roster",
    "list_session_facilitators",
    "list_sessions",
    "list_workshops",
    "mark_attendance",
    "remove_session_facilitator",
    "seat_counts",
]
