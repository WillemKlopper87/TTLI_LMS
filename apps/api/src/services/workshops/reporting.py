"""Workshop/booking read models — facilitator listings, public browse,
seat counts, "my sessions" and the calendar-export context. Split out of
the former monolithic `services/workshops.py` (TTLI_Audit_Report_2026-09-02.md
M6); see `src/services/workshops/__init__.py` for the split's rationale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import Forbidden, NotFound
from src.models.user import User
from src.models.workshop import (
    Booking,
    Facilitator,
    MeetingLink,
    SessionFacilitator,
    Workshop,
    WorkshopSession,
)
from src.services.workshops.errors import WorkshopError


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
    "CoachingFacilitatorRow",
    "FacilitatorRow",
    "OwnBookingRow",
    "get_booking_ics_context",
    "list_coaching_facilitators",
    "list_facilitators",
    "list_own_bookings",
    "list_public_one_on_one_workshops",
    "list_public_sessions",
    "list_session_facilitators",
    "list_sessions",
    "seat_counts",
]
