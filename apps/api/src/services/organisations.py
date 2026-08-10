"""Organisations, seats (02 §4.5, REQ-TEN-02). See 0016's migration
docstring for the seat model: a null-`user_id` entitlement is the
purchased pool, a set-`user_id` entitlement drawn from it is one
assigned seat, and "available seats" is computed from both rather than
tracked as a separate counter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, Forbidden, NotFound
from src.core.ids import uuid7
from src.models.commerce import Entitlement
from src.models.course import Course
from src.models.organisation import RELATIONSHIP_VALUES, Organisation, OrganisationMember
from src.models.user import User
from src.services import enrolment as enrolment_service
from src.services import entitlements, identity


class OrganisationError(AppError):
    """A refusal in the organisation/seat flow — not a member, not an
    admin, or no seats left."""

    code = "ORGANISATION_ERROR"


async def create_organisation(
    session: AsyncSession, *, tenant_id: uuid.UUID, name: str, creator_user_id: uuid.UUID
) -> Organisation:
    """Self-service — any authenticated user can start an organisation
    and becomes its first admin. There is no signup flow yet (Phase 1
    scope), so the realistic actor here already has an account from an
    earlier individual purchase or an admin-created one."""
    organisation = Organisation(id=uuid7(), tenant_id=tenant_id, name=name)
    session.add(organisation)
    await session.flush()
    session.add(
        OrganisationMember(
            id=uuid7(),
            tenant_id=tenant_id,
            organisation_id=organisation.id,
            user_id=creator_user_id,
            relationship="admin",
        )
    )
    await session.flush()
    return organisation


async def _get_membership(
    session: AsyncSession, *, organisation_id: uuid.UUID, user_id: uuid.UUID
) -> OrganisationMember | None:
    stmt = select(OrganisationMember).where(
        OrganisationMember.organisation_id == organisation_id,
        OrganisationMember.user_id == user_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def require_membership(
    session: AsyncSession, *, tenant_id: uuid.UUID, organisation_id: uuid.UUID, user_id: uuid.UUID
) -> Organisation:
    organisation = await session.get(Organisation, organisation_id)
    if organisation is None or organisation.tenant_id != tenant_id:
        raise NotFound("No such organisation.")
    if await _get_membership(session, organisation_id=organisation_id, user_id=user_id) is None:
        raise Forbidden("You are not a member of this organisation.")
    return organisation


async def require_admin(
    session: AsyncSession, *, tenant_id: uuid.UUID, organisation_id: uuid.UUID, user_id: uuid.UUID
) -> Organisation:
    organisation = await session.get(Organisation, organisation_id)
    if organisation is None or organisation.tenant_id != tenant_id:
        raise NotFound("No such organisation.")
    membership = await _get_membership(session, organisation_id=organisation_id, user_id=user_id)
    if membership is None or membership.relationship != "admin":
        raise Forbidden("Only an organisation admin can do this.")
    return organisation


@dataclass(frozen=True, slots=True)
class MemberRow:
    user_id: uuid.UUID
    email: str
    relationship: str


async def list_members(
    session: AsyncSession, crypto: CryptoBox, *, organisation_id: uuid.UUID
) -> list[MemberRow]:
    stmt = (
        select(OrganisationMember, User)
        .join(User, User.id == OrganisationMember.user_id)
        .where(OrganisationMember.organisation_id == organisation_id)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MemberRow(
            user_id=member.user_id,
            email=crypto.decrypt(user.email_encrypted),
            relationship=member.relationship,
        )
        for member, user in rows
    ]


async def _pool_entitlements(
    session: AsyncSession, *, organisation_id: uuid.UUID, course_id: uuid.UUID
) -> list[Entitlement]:
    """Every pool entitlement (user_id NULL) this org has bought for this
    course, across every order that ever purchased seats for it — each
    one traceable back to the order that funded it (02 §4.7:
    source_order_id is "never null in production data")."""
    stmt = select(Entitlement).where(
        Entitlement.organisation_id == organisation_id,
        Entitlement.target_id == course_id,
        Entitlement.kind == "course",
        Entitlement.user_id.is_(None),
    )
    return list((await session.execute(stmt)).scalars().all())


async def _seat_totals(
    session: AsyncSession, *, organisation_id: uuid.UUID, course_id: uuid.UUID
) -> tuple[int, int]:
    """(purchased, assigned) — assigned is the count of active
    (non-revoked) seats drawn from the pool. Computed on read, not
    cached, so a revoke is immediately reflected in what's available."""
    pool = await _pool_entitlements(session, organisation_id=organisation_id, course_id=course_id)
    purchased = sum((e.quantity or 0) for e in pool)

    assigned_stmt = select(Entitlement.id).where(
        Entitlement.organisation_id == organisation_id,
        Entitlement.target_id == course_id,
        Entitlement.kind == "course",
        Entitlement.user_id.is_not(None),
        Entitlement.revoked_at.is_(None),
    )
    assigned = len((await session.execute(assigned_stmt)).all())
    return purchased, assigned


@dataclass(frozen=True, slots=True)
class SeatAssignmentResult:
    email: str
    ok: bool
    reason: str | None


async def assign_seat(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    course_id: uuid.UUID,
    email: str,
) -> SeatAssignmentResult:
    """Draws one seat from the organisation's pool for this course and
    grants it — find-or-create the employee's account (same pattern
    services/guest_access.py::grant uses), a real entitlement, and a
    real enrolment, exactly as an individual purchase would, just
    without a second order."""
    pool = await _pool_entitlements(session, organisation_id=organisation_id, course_id=course_id)
    purchased = sum((e.quantity or 0) for e in pool)
    assigned_stmt = select(Entitlement.id).where(
        Entitlement.organisation_id == organisation_id,
        Entitlement.target_id == course_id,
        Entitlement.kind == "course",
        Entitlement.user_id.is_not(None),
        Entitlement.revoked_at.is_(None),
    )
    assigned = len((await session.execute(assigned_stmt)).all())
    if assigned >= purchased or not pool:
        return SeatAssignmentResult(email=email, ok=False, reason="No seats remaining.")
    # Most recent purchase funds this assignment — real provenance, not a
    # null placeholder (02 §4.7's source_order_id is meant to always
    # trace back to the order that paid for it).
    funding_order_id = max(pool, key=lambda e: e.granted_at).source_order_id

    course = await session.get(Course, course_id)
    if course is None:
        return SeatAssignmentResult(email=email, ok=False, reason="No such course.")

    existing = await identity.find_by_email(session, crypto, email)
    if existing is not None:
        user = existing
    else:
        user = await identity.create_user(session, crypto, tenant_id=tenant_id, email=email)

    already = await _get_membership(session, organisation_id=organisation_id, user_id=user.id)
    if already is None:
        session.add(
            OrganisationMember(
                id=uuid7(),
                tenant_id=tenant_id,
                organisation_id=organisation_id,
                user_id=user.id,
                relationship="member",
            )
        )

    if funding_order_id is None:  # pragma: no cover - order fulfilment always sets this
        return SeatAssignmentResult(
            email=email, ok=False, reason="This seat pool has no order on record."
        )

    entitlement = await entitlements.grant(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        source_order_id=funding_order_id,
        kind="course",
        target_id=course_id,
        quantity=1,
    )
    entitlement.organisation_id = organisation_id
    await enrolment_service.get_or_create_enrolment(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        course_id=course_id,
        entitlement_id=entitlement.id,
    )
    await session.flush()
    return SeatAssignmentResult(email=email, ok=True, reason=None)


async def assign_seats_bulk(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    course_id: uuid.UUID,
    emails: list[str],
) -> list[SeatAssignmentResult]:
    results = []
    for email in emails:
        results.append(
            await assign_seat(
                session,
                crypto,
                tenant_id=tenant_id,
                organisation_id=organisation_id,
                course_id=course_id,
                email=email,
            )
        )
    return results


async def revoke_seat(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    entitlement_id: uuid.UUID,
) -> None:
    """Frees the seat back to the pool for reassignment. Does not
    retroactively remove the enrolment already created — REQ-TEN-02 asks
    for seat reassignment, not a course-access-revocation flow, and
    unwinding an enrolment mid-course is a bigger, separate product
    question (tracked in STATUS.md, not answered by guessing here)."""
    entitlement = await session.get(Entitlement, entitlement_id)
    if (
        entitlement is None
        or entitlement.tenant_id != tenant_id
        or entitlement.organisation_id != organisation_id
        or entitlement.user_id is None
    ):
        raise NotFound("No such assigned seat.")
    if entitlement.revoked_at is not None:
        raise OrganisationError("This seat has already been revoked.")
    entitlement.revoked_at = datetime.now(UTC)
    await session.flush()


@dataclass(frozen=True, slots=True)
class AssignedSeatRow:
    entitlement_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    granted_at: datetime


async def list_assigned_seats(
    session: AsyncSession, crypto: CryptoBox, *, organisation_id: uuid.UUID, course_id: uuid.UUID
) -> list[AssignedSeatRow]:
    """Every active (non-revoked) assigned seat for one course — what the
    revoke UI needs that the aggregate `/seats` summary can't provide."""
    stmt = (
        select(Entitlement, User)
        .join(User, User.id == Entitlement.user_id)
        .where(
            Entitlement.organisation_id == organisation_id,
            Entitlement.target_id == course_id,
            Entitlement.kind == "course",
            Entitlement.user_id.is_not(None),
            Entitlement.revoked_at.is_(None),
        )
        .order_by(Entitlement.granted_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        AssignedSeatRow(
            entitlement_id=entitlement.id,
            user_id=entitlement.user_id,
            email=crypto.decrypt(user.email_encrypted),
            granted_at=entitlement.granted_at,
        )
        for entitlement, user in rows
    ]


@dataclass(frozen=True, slots=True)
class SeatSummary:
    course_id: uuid.UUID
    course_title: str
    purchased: int
    assigned: int


async def list_seat_summaries(
    session: AsyncSession, *, organisation_id: uuid.UUID
) -> list[SeatSummary]:
    course_ids_stmt = (
        select(Entitlement.target_id)
        .where(
            Entitlement.organisation_id == organisation_id,
            Entitlement.kind == "course",
            Entitlement.user_id.is_(None),
        )
        .distinct()
    )
    course_ids = (await session.execute(course_ids_stmt)).scalars().all()

    summaries = []
    for course_id in course_ids:
        course = await session.get(Course, course_id)
        if course is None:  # pragma: no cover - FK guarantees this
            continue
        purchased, assigned = await _seat_totals(
            session, organisation_id=organisation_id, course_id=course_id
        )
        summaries.append(
            SeatSummary(
                course_id=course_id,
                course_title=course.title,
                purchased=purchased,
                assigned=assigned,
            )
        )
    return summaries


__all__ = [
    "RELATIONSHIP_VALUES",
    "AssignedSeatRow",
    "MemberRow",
    "OrganisationError",
    "SeatAssignmentResult",
    "SeatSummary",
    "assign_seat",
    "assign_seats_bulk",
    "create_organisation",
    "list_assigned_seats",
    "list_members",
    "list_seat_summaries",
    "require_admin",
    "require_membership",
    "revoke_seat",
]
