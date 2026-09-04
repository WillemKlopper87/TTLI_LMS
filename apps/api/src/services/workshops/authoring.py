"""Workshop/facilitator/session authoring — the half of 02 §9 that an
admin or facilitator manages ahead of any booking. Split out of the
former monolithic `services/workshops.py` (TTLI_Audit_Report_2026-09-02.md
M6); see `src/services/workshops/__init__.py` for the split's rationale.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import NotFound
from src.core.ids import uuid7
from src.models.workshop import (
    Facilitator,
    FacilitatorAvailability,
    SessionFacilitator,
    Workshop,
    WorkshopSession,
)
from src.services.workshops.errors import WorkshopError


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


__all__ = [
    "add_availability",
    "add_session_facilitator",
    "create_facilitator",
    "create_session",
    "create_workshop",
    "list_availability",
    "list_workshops",
    "remove_session_facilitator",
    "update_workshop",
]
