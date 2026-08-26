"""Workshops, facilitators, booking (02 §9, REQ-WS-01 through REQ-WS-09).
See `0018`'s migration docstring for what this sprint deliberately
deferred and why.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.crypto import CryptoBox
from src.core.errors import AppError, Forbidden, NotFound
from src.core.ids import uuid7
from src.core.logging import get_logger
from src.models.audit import AuditAction
from src.models.commerce import Entitlement
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
from src.services.meeting.base import MeetingProviderUnavailable

log = get_logger(__name__)


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


@dataclass(frozen=True, slots=True)
class CoachingFacilitatorRow:
    id: uuid.UUID
    display_name: str
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


async def list_coaching_facilitators(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    workshop_id: uuid.UUID,
) -> list[CoachingFacilitatorRow]:
    """Return the minimum facilitator identity needed by the booking UI."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.tenant_id != tenant_id:
        raise NotFound("No such workshop.")
    if workshop.session_type != "one_on_one":
        raise WorkshopError("Coaches are only listed for one-on-one workshops.")

    stmt = (
        select(Facilitator, User)
        .join(User, User.id == Facilitator.user_id)
        .where(Facilitator.tenant_id == tenant_id, User.deleted_at.is_(None))
        .order_by(Facilitator.created_at, Facilitator.id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        CoachingFacilitatorRow(
            id=facilitator.id,
            display_name=(
                crypto.decrypt(user.full_name_encrypted).strip()
                if user.full_name_encrypted
                else "Coach"
            ),
            bio=facilitator.bio,
            timezone=facilitator.timezone,
        )
        for facilitator, user in rows
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


async def update_workshop(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workshop_id: uuid.UUID,
    requires_credit: bool | None = None,
    meeting_provider: str | None = None,
) -> Workshop:
    """Flips the credit gate (Phase 4) and/or the meeting provider
    (Phase 5) — either independently, since the router only ever sends
    the one field its own control changed. Existing sessions/bookings
    are untouched either way — both are only read at the moment a new
    `book_session` call is made."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.tenant_id != tenant_id:
        raise NotFound("No such workshop.")
    if requires_credit is not None:
        workshop.requires_credit = requires_credit
    if meeting_provider is not None:
        workshop.meeting_provider = meeting_provider
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


MAX_OPEN_SLOT_RANGE_DAYS = 14


async def list_open_slots(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workshop_id: uuid.UUID,
    facilitator_id: uuid.UUID,
    from_date: date,
    to_date: date,
) -> list[tuple[datetime, datetime]]:
    """P13/REQ-WS-01/02: self-service slot picking for `one_on_one`
    workshops — expands a facilitator's weekly `FacilitatorAvailability`
    windows into concrete, bookable `(starts_at, ends_at)` candidates
    over a bounded date range, minus whatever they're already scheduled
    for. Every other session type keeps the admin-scheduled model
    (`create_session`) unchanged; `session_type` is otherwise purely
    descriptive everywhere else in this module.

    Read-only — computing a slot is not a reservation. Two learners can
    see (and pick) the same slot; `book_open_slot` is what actually
    serialises the claim."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.tenant_id != tenant_id:
        raise NotFound("No such workshop.")
    if workshop.session_type != "one_on_one":
        raise WorkshopError("Self-service slot picking is only available for one-on-one workshops.")
    facilitator = await session.get(Facilitator, facilitator_id)
    if facilitator is None or facilitator.tenant_id != tenant_id:
        raise NotFound("No such facilitator.")
    if to_date < from_date:
        raise WorkshopError("The date range's end must not be before its start.")
    if (to_date - from_date).days > MAX_OPEN_SLOT_RANGE_DAYS:
        raise WorkshopError(f"Date ranges are capped at {MAX_OPEN_SLOT_RANGE_DAYS} days.")

    duration = timedelta(minutes=workshop.default_duration_minutes)
    windows = await list_availability(session, facilitator_id=facilitator_id)
    if not windows:
        return []

    # Loaded once for the whole range rather than re-querying per
    # candidate slot — the query _facilitator_has_conflict runs one at a
    # time is the same shape, just batched here since candidates can
    # number in the dozens for a two-week range.
    range_start = datetime.combine(from_date, time.min, tzinfo=UTC)
    range_end = datetime.combine(to_date, time.max, tzinfo=UTC)
    busy_stmt = (
        select(WorkshopSession.starts_at, WorkshopSession.ends_at)
        .join(SessionFacilitator, SessionFacilitator.session_id == WorkshopSession.id)
        .where(
            SessionFacilitator.facilitator_id == facilitator_id,
            WorkshopSession.status == "scheduled",
            WorkshopSession.starts_at < range_end,
            WorkshopSession.ends_at > range_start,
        )
    )
    busy = (await session.execute(busy_stmt)).all()

    now = datetime.now(UTC)
    slots: list[tuple[datetime, datetime]] = []
    day = from_date
    while day <= to_date:
        weekday = day.weekday()
        for w in windows:
            if w.day_of_week != weekday:
                continue
            slot_start = datetime.combine(day, w.start_time, tzinfo=UTC)
            window_end = datetime.combine(day, w.end_time, tzinfo=UTC)
            while slot_start + duration <= window_end:
                slot_end = slot_start + duration
                if slot_start > now and not any(
                    slot_start < b_end and slot_end > b_start for b_start, b_end in busy
                ):
                    slots.append((slot_start, slot_end))
                slot_start += duration
        day += timedelta(days=1)
    return slots


async def book_open_slot(
    session: AsyncSession,
    crypto: CryptoBox,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    workshop_id: uuid.UUID,
    facilitator_id: uuid.UUID,
    starts_at: datetime,
    user_id: uuid.UUID,
) -> Booking:
    """Create-and-claim, atomically. A learner only ever reaches this
    with a slot `list_open_slots` computed, but that computation is not
    itself a reservation — two learners could pick the same slot in the
    same instant, since neither claims anything until this runs.
    Locking the `Facilitator` row (there is no session row yet to lock)
    serialises every concurrent create-and-claim attempt for this
    facilitator — the same "lock the parent to serialise the child
    insert" shape `book_session`'s own `FOR UPDATE` on the session row
    already uses for the last-seat race."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.tenant_id != tenant_id:
        raise NotFound("No such workshop.")
    if workshop.session_type != "one_on_one":
        raise WorkshopError("Self-service slot picking is only available for one-on-one workshops.")

    facilitator = (
        await session.execute(
            select(Facilitator).where(Facilitator.id == facilitator_id).with_for_update()
        )
    ).scalar_one_or_none()
    if facilitator is None or facilitator.tenant_id != tenant_id:
        raise NotFound("No such facilitator.")

    if starts_at <= datetime.now(UTC):
        raise WorkshopError("This slot is no longer in the future.")
    ends_at = starts_at + timedelta(minutes=workshop.default_duration_minutes)
    if not await _facilitator_available_at(
        session, facilitator_id=facilitator_id, starts_at=starts_at, ends_at=ends_at
    ):
        raise WorkshopError("This falls outside the facilitator's stated availability.")
    if await _facilitator_has_conflict(
        session, facilitator_id=facilitator_id, starts_at=starts_at, ends_at=ends_at
    ):
        raise WorkshopError("This slot was just taken — please pick another.")

    workshop_session = WorkshopSession(
        id=uuid7(),
        tenant_id=tenant_id,
        workshop_id=workshop_id,
        facilitator_id=facilitator_id,
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=1,
    )
    session.add(workshop_session)
    await session.flush()
    session.add(
        SessionFacilitator(
            id=uuid7(),
            tenant_id=tenant_id,
            session_id=workshop_session.id,
            facilitator_id=facilitator_id,
        )
    )
    await session.flush()

    return await book_session(
        session,
        crypto,
        settings,
        tenant_id=tenant_id,
        session_id=workshop_session.id,
        user_id=user_id,
    )


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
    active booking (refunding any credit each one consumed, via
    `_cancel_booking_row`), cancels the provider meeting, and tells
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
        try:
            await provider.cancel_meeting(provider_meeting_id=link.provider_meeting_id)
        except MeetingProviderUnavailable:
            # overall-review F3: fail-soft here, not fail-closed like
            # create_meeting — a Graph outage must not block an admin
            # from cancelling a session (every booking on it is being
            # cancelled in this same transaction regardless). The
            # session's calendar event is left stale rather than the
            # cancellation itself being blocked.
            log.warning(
                "workshop_meeting_cancel_failed",
                session_id=str(session_id),
                provider=link.provider,
            )

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


async def list_public_one_on_one_workshops(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Workshop]:
    """P13: `one_on_one` workshops for the public browse page. Unlike
    `list_public_sessions`, these have no pre-created `WorkshopSession`
    rows to list — a visitor discovers the workshop itself, then picks
    a facilitator and a slot on the self-service booking page
    (`list_open_slots`/`book_open_slot`)."""
    stmt = (
        select(Workshop)
        .where(Workshop.tenant_id == tenant_id, Workshop.session_type == "one_on_one")
        .order_by(Workshop.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _consume_workshop_credit(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, workshop_id: uuid.UUID
) -> uuid.UUID:
    """P7 phase 4: draws one credit from the learner's oldest valid
    `workshop_credit` entitlement for this workshop — same revoked/
    expired filter `entitlements.py::has_valid_course_entitlement`
    already established, so a lapsed/refunded credit pack can't be
    drawn from just because a row still exists. `book_session` is the
    only caller, and only when `Workshop.requires_credit` is set."""
    now = datetime.now(UTC)
    stmt = (
        select(Entitlement)
        .where(
            Entitlement.tenant_id == tenant_id,
            Entitlement.user_id == user_id,
            Entitlement.kind == "workshop_credit",
            Entitlement.target_id == workshop_id,
            Entitlement.revoked_at.is_(None),
            (Entitlement.expires_at.is_(None)) | (Entitlement.expires_at > now),
            Entitlement.quantity > 0,
        )
        .order_by(Entitlement.granted_at)
        # FOR UPDATE (overall-review F1): without it, two concurrent
        # bookings of *different* sessions of the same workshop both
        # read quantity == 1, both decrement, and one paid credit buys
        # two seats. The lock makes the second transaction wait, re-read
        # the committed quantity of 0, find no row passing the filter,
        # and refuse — the same idiom services/invoicing.py already uses
        # for its money-adjacent counter.
        .with_for_update()
    )
    entitlement = (await session.execute(stmt)).scalars().first()
    if entitlement is None:
        raise WorkshopError("No workshop credits remaining — purchase a session pack.")
    entitlement.quantity = (entitlement.quantity or 0) - 1
    await session.flush()
    return entitlement.id


async def _refund_workshop_credit(session: AsyncSession, *, entitlement_id: uuid.UUID) -> None:
    """The `_cancel_booking_row` half of the pair above — always
    refunds, no cancellation-deadline logic invented since none is
    specified anywhere in the requirements this phase closes.

    An in-database increment, not read-modify-write (overall-review F1's
    sibling): `SET quantity = quantity + 1` is atomic under concurrent
    writers, so it needs no lock of its own and cannot lose an update to
    a simultaneous consume/refund on the same entitlement."""
    await session.execute(
        update(Entitlement)
        .where(Entitlement.id == entitlement_id)
        .values(quantity=func.coalesce(Entitlement.quantity, 0) + 1)
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
    # FOR UPDATE on the session row (overall-review F6): seat_counts()
    # below is a check-then-insert, so two learners racing for the last
    # seat could otherwise both count `registered < capacity` and both
    # register. Locking the parent row serialises bookings per session
    # (contention is per-session, not global). An explicit locked SELECT
    # rather than session.get(..., with_for_update=True) because the
    # reschedule path has already loaded this row into the identity map,
    # and session.get would then return it without emitting SQL — no
    # lock at all; populate_existing refreshes any such stale copy from
    # the locked read.
    workshop_session = (
        await session.execute(
            select(WorkshopSession)
            .where(WorkshopSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if workshop_session is None or workshop_session.tenant_id != tenant_id:
        raise NotFound("No such session.")
    if workshop_session.status != "scheduled":
        raise WorkshopError("This session is no longer taking bookings.")
    workshop = await session.get(Workshop, workshop_session.workshop_id)
    if workshop is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such workshop.")

    existing = (
        await session.execute(
            select(Booking).where(Booking.session_id == session_id, Booking.user_id == user_id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status != "cancelled":
        raise WorkshopError("You already have a booking for this session.")

    registered, _ = await seat_counts(session, session_id=session_id)
    status = "registered" if registered < workshop_session.capacity else "waitlisted"

    # P7 phase 4: a credit is spent to claim a spot, waitlisted or not
    # — refunded on any cancellation below, same as a registered spot's
    # credit would be. Consuming only on confirmed registration would
    # leave a later waitlist promotion (_cancel_booking_row's own logic)
    # with no credit ever drawn for a seat that did fill.
    consumed_entitlement_id: uuid.UUID | None = None
    if workshop.requires_credit:
        consumed_entitlement_id = await _consume_workshop_credit(
            session, tenant_id=tenant_id, user_id=user_id, workshop_id=workshop.id
        )

    if existing is not None:
        existing.status = status
        existing.consumed_entitlement_id = consumed_entitlement_id
        booking = existing
    else:
        booking = Booking(
            id=uuid7(),
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            status=status,
            consumed_entitlement_id=consumed_entitlement_id,
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
        provider = meeting_service.get_provider(workshop.meeting_provider, settings=settings)
        link = (
            await session.execute(select(MeetingLink).where(MeetingLink.session_id == session_id))
        ).scalar_one_or_none()
        if link is None:
            primary_facilitator = await session.get(Facilitator, workshop_session.facilitator_id)
            organiser_user_id = (
                primary_facilitator.user_id if primary_facilitator is not None else user_id
            )
            facilitator_rows = await list_session_facilitators(
                session, crypto, session_id=session_id
            )
            details = await provider.create_meeting(
                session=workshop_session,
                organiser_user_id=organiser_user_id,
                attendee_emails=[f.email for f in facilitator_rows],
            )
            link = MeetingLink(
                id=uuid7(),
                tenant_id=tenant_id,
                session_id=session_id,
                provider=details.provider,
                provider_meeting_id=details.provider_meeting_id,
                join_url=details.join_url,
                organiser_user_id=organiser_user_id,
            )
            session.add(link)
            await session.flush()

        # A session's meeting is created with only its facilitator(s) as
        # attendees (nobody's booked yet) — every registrant, including
        # the one who just triggered creation above, is added here, one
        # at a time, so a real invite (REQ-WS-05) reaches them too.
        learner = await session.get(User, user_id)
        if learner is not None:
            try:
                await provider.add_attendee(
                    provider_meeting_id=link.provider_meeting_id,
                    email=crypto.decrypt(learner.email_encrypted),
                )
            except MeetingProviderUnavailable:
                # overall-review F3: fail-soft, not fail-closed. The
                # booking itself (a real seat, a real credit spend) is
                # already committed above via a real Graph outage
                # blocking a paying learner from completing a booking
                # would be worse than the alternative here — a stale
                # invite the facilitator can send by hand meanwhile,
                # the same manual-fallback posture the `manual`
                # provider already establishes for REQ-WS-06.
                log.warning(
                    "workshop_add_attendee_failed",
                    session_id=str(session_id),
                    booking_id=str(booking.id),
                    provider=provider.name,
                )

    await session.flush()
    return booking


async def reschedule_booking(
    session: AsyncSession,
    crypto: CryptoBox,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    booking_id: uuid.UUID,
    target_session_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> Booking:
    """P7, REQ-WS-03: cancel-then-rebook in one call, against a
    different session of the *same* workshop — reschedule stays
    modelled as cancel-then-rebook (0018's own explicit, reasoned
    deferral, not relitigated here), the missing piece was only the
    convenience wrapper and marking the old booking `"rescheduled"`
    instead of `"cancelled"`, the `attendance_status` value that's
    existed unused since `0018`. Learner-initiated only — a facilitator
    reschedules by cancelling and letting the learner rebook, the same
    ownership split `cancel_booking` draws for who may act."""
    booking = await session.get(Booking, booking_id)
    if booking is None or booking.tenant_id != tenant_id:
        raise NotFound("No such booking.")
    if booking.status == "cancelled":
        raise WorkshopError("This booking is already cancelled.")
    if booking.user_id != actor_user_id:
        raise Forbidden("You do not have access to this booking.")
    if booking.session_id == target_session_id:
        raise WorkshopError("Choose a different session to reschedule to.")

    old_session = await session.get(WorkshopSession, booking.session_id)
    target_session = await session.get(WorkshopSession, target_session_id)
    if (
        old_session is None  # pragma: no cover - FK guarantees this
        or target_session is None
        or target_session.tenant_id != tenant_id
    ):
        raise NotFound("No such session.")
    if target_session.workshop_id != old_session.workshop_id:
        raise WorkshopError("Reschedule only moves you to another session of the same workshop.")

    # A credit transfer, not a double-charge, when the workshop requires
    # one: _cancel_booking_row refunds whatever the old booking consumed,
    # book_session below consumes fresh for the target — same workshop,
    # so a requires_credit workshop nets to zero credits spent overall.
    await _cancel_booking_row(
        session, booking=booking, resulting_status="rescheduled", settings=settings, crypto=crypto
    )
    return await book_session(
        session,
        crypto,
        settings,
        tenant_id=tenant_id,
        session_id=target_session_id,
        user_id=actor_user_id,
    )


async def _cancel_booking_row(
    session: AsyncSession,
    *,
    booking: Booking,
    resulting_status: str = "cancelled",
    settings: Settings | None = None,
    crypto: CryptoBox | None = None,
) -> None:
    """The actual state transition, shared by `cancel_booking` (one
    booking, permission-checked), `cancel_session` (every booking on a
    session, already permission-checked once by its caller) and
    `reschedule_booking` — same waitlist-promotion and attendance-record
    bookkeeping either way. `resulting_status` is `"cancelled"`
    normally, `"rescheduled"` when called from `reschedule_booking`
    (Phase 2) — the `attendance_status` enum has carried that value,
    unused, since `0018`.

    Always refunds a consumed workshop credit (Phase 4) — no
    cancellation-deadline forfeiture is specified anywhere, so none is
    invented here.

    `settings`/`crypto` (Phase 5) drive removing the cancelled learner —
    and adding a promoted one — as a real meeting attendee. Both
    optional: `cancel_session` cancels the whole session's meeting right
    after this returns, so per-booking attendee edits there would be
    wasted Graph calls against a meeting about to be deleted; it
    deliberately leaves both unset."""
    was_registered = booking.status == "registered"
    booking.status = "cancelled"

    if booking.consumed_entitlement_id is not None:
        await _refund_workshop_credit(session, entitlement_id=booking.consumed_entitlement_id)

    record = (
        await session.execute(
            select(AttendanceRecord).where(AttendanceRecord.booking_id == booking.id)
        )
    ).scalar_one_or_none()
    if record is not None:
        record.status = resulting_status

    provider = None
    link = None
    meeting_crypto = crypto
    if settings is not None and meeting_crypto is not None:
        link = (
            await session.execute(
                select(MeetingLink).where(MeetingLink.session_id == booking.session_id)
            )
        ).scalar_one_or_none()
        if link is not None:
            provider = meeting_service.get_provider(link.provider, settings=settings)
        else:
            meeting_crypto = None
    else:
        meeting_crypto = None

    if was_registered:
        if provider is not None and link is not None and meeting_crypto is not None:
            cancelled_learner = await session.get(User, booking.user_id)
            if cancelled_learner is not None:
                try:
                    await provider.remove_attendee(
                        provider_meeting_id=link.provider_meeting_id,
                        email=meeting_crypto.decrypt(cancelled_learner.email_encrypted),
                    )
                except MeetingProviderUnavailable:
                    # overall-review F3: fail-soft — a Graph outage
                    # must not block the cancellation itself (which
                    # already freed the seat/refunded the credit
                    # above). A stale invite for the cancelled learner
                    # is the acceptable side effect.
                    log.warning(
                        "workshop_remove_attendee_failed",
                        booking_id=str(booking.id),
                        provider=provider.name,
                    )

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

            if provider is not None and link is not None and meeting_crypto is not None:
                promoted_learner = await session.get(User, next_in_line.user_id)
                if promoted_learner is not None:
                    try:
                        await provider.add_attendee(
                            provider_meeting_id=link.provider_meeting_id,
                            email=meeting_crypto.decrypt(promoted_learner.email_encrypted),
                        )
                    except MeetingProviderUnavailable:
                        # overall-review F3: fail-soft — the promotion
                        # itself (a real seat, already committed above)
                        # must not be blocked by a Graph outage.
                        log.warning(
                            "workshop_promote_add_attendee_failed",
                            booking_id=str(next_in_line.id),
                            provider=provider.name,
                        )

    await session.flush()


async def cancel_booking(
    session: AsyncSession,
    crypto: CryptoBox,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    booking_id: uuid.UUID,
    actor_user_id: uuid.UUID,
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

    await _cancel_booking_row(
        session, booking=booking, resulting_status="cancelled", settings=settings, crypto=crypto
    )


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


@dataclass(frozen=True, slots=True)
class OwnBookingRow:
    booking_id: uuid.UUID
    session_id: uuid.UUID
    workshop_id: uuid.UUID
    workshop_title: str
    facilitator_names: list[str]
    starts_at: datetime
    ends_at: datetime
    status: str
    session_status: str
    join_url: str | None
    provider: str | None
    # Whether cancel/reschedule are still meaningful actions — a
    # cancelled booking, or one on a session that's already cancelled
    # or in the past, has neither (P7: the "my sessions" page uses this
    # instead of re-deriving the same rule client-side).
    can_manage: bool


async def list_own_bookings(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> list[OwnBookingRow]:
    """Mirrors `enrolment_service.list_own_enrolments`/P5's `list_own_
    path_enrolments` — the learner's own "my sessions" page (P7), a real
    gap before this pass: a booking's own workflow (cancel/reschedule)
    had no listing endpoint scoped to "mine," only `/learn/dashboard`'s
    read-only "Coming up" rowlist and the admin/facilitator-oriented
    `GET /workshops/{id}/sessions`."""
    stmt = (
        select(Booking, WorkshopSession, Workshop)
        .join(WorkshopSession, WorkshopSession.id == Booking.session_id)
        .join(Workshop, Workshop.id == WorkshopSession.workshop_id)
        .where(Booking.tenant_id == tenant_id, Booking.user_id == user_id)
        .order_by(WorkshopSession.starts_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    now = datetime.now(UTC)
    out: list[OwnBookingRow] = []
    for booking, workshop_session, workshop in rows:
        facilitators = await list_session_facilitators(
            session, crypto, session_id=workshop_session.id
        )
        link = (
            await session.execute(
                select(MeetingLink).where(MeetingLink.session_id == workshop_session.id)
            )
        ).scalar_one_or_none()
        out.append(
            OwnBookingRow(
                booking_id=booking.id,
                session_id=workshop_session.id,
                workshop_id=workshop.id,
                workshop_title=workshop.title,
                facilitator_names=[f.email for f in facilitators],
                starts_at=workshop_session.starts_at,
                ends_at=workshop_session.ends_at,
                status=booking.status,
                session_status=workshop_session.status,
                join_url=link.join_url if link else None,
                provider=link.provider if link else None,
                can_manage=(
                    booking.status != "cancelled"
                    and workshop_session.status == "scheduled"
                    and workshop_session.starts_at > now
                ),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class BookingIcsContext:
    booking: Booking
    workshop_session: WorkshopSession
    workshop: Workshop
    facilitator_names: list[str]


async def get_booking_ics_context(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    booking_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> BookingIcsContext:
    """P7 phase 3, REQ-WS-05: everything `routers/workshops.py`'s
    `GET /bookings/{id}/calendar.ics` needs to build an `IcsEvent` —
    booking-owner-only, the same ownership rule `reschedule_booking`
    draws (a facilitator downloads a session's own calendar entry
    through their own booking, not someone else's)."""
    booking = await session.get(Booking, booking_id)
    if booking is None or booking.tenant_id != tenant_id:
        raise NotFound("No such booking.")
    if booking.user_id != actor_user_id:
        raise Forbidden("You do not have access to this booking.")

    workshop_session = await session.get(WorkshopSession, booking.session_id)
    if workshop_session is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such session.")
    workshop = await session.get(Workshop, workshop_session.workshop_id)
    if workshop is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such workshop.")

    facilitators = await list_session_facilitators(session, crypto, session_id=workshop_session.id)
    return BookingIcsContext(
        booking=booking,
        workshop_session=workshop_session,
        workshop=workshop,
        facilitator_names=[f.email for f in facilitators],
    )


__all__ = [
    "BookingIcsContext",
    "FacilitatorRow",
    "OwnBookingRow",
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
    "get_booking_ics_context",
    "list_availability",
    "list_facilitators",
    "list_own_bookings",
    "list_public_sessions",
    "list_roster",
    "list_session_facilitators",
    "list_sessions",
    "list_workshops",
    "mark_attendance",
    "remove_session_facilitator",
    "reschedule_booking",
    "seat_counts",
    "update_workshop",
]
