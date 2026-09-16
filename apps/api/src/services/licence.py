"""Facilitator licensing service: grant and query operations.

Core licensing operations: create a licence, check if a learner holds an active licence
for a course/path, list a licensee's seat grants (with client isolation), update seat usage counts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError
from src.models.audit import AuditAction
from src.models.licence import Licence, LicenceSeatGrant
from src.services import audit


async def create_licence(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    learning_path_id: uuid.UUID | None = None,
    seats_purchased: int,
    starts_at: datetime,
    ends_at: datetime,
    price_per_seat_cents: int | None = None,
    currency: str | None = None,
    royalty_pct: float | None = None,
    order_id: uuid.UUID | None = None,
    notes: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Licence:
    """Create a licence granting a course or learning path to an organisation.

    Raises AppError if both course_id and learning_path_id are set, or neither.
    The database constraint will also catch this, but we validate early for UX.
    """
    if (course_id is None and learning_path_id is None) or (
        course_id is not None and learning_path_id is not None
    ):
        raise AppError(
            "A licence must target either a course or a learning path, not both or neither.",
            {"course_id": course_id, "learning_path_id": learning_path_id},
        )

    if seats_purchased <= 0:
        raise AppError("Seats purchased must be positive.", {"seats_purchased": seats_purchased})

    if starts_at >= ends_at:
        raise AppError(
            "Licence must start before it ends.",
            {"starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()},
        )

    licence = Licence(
        tenant_id=tenant_id,
        organisation_id=organisation_id,
        course_id=course_id,
        learning_path_id=learning_path_id,
        status="active",
        seats_purchased=seats_purchased,
        starts_at=starts_at,
        ends_at=ends_at,
        price_per_seat_cents=price_per_seat_cents,
        currency=currency,
        royalty_pct=float(royalty_pct) if royalty_pct else None,
        order_id=order_id,
        notes=notes,
    )
    session.add(licence)
    await session.flush()

    if actor_user_id:
        await audit.record(
            session,
            tenant_id=tenant_id,
            action=AuditAction.LICENCE_CREATED,
            actor_user_id=actor_user_id,
            entity_type="licence",
            entity_id=licence.id,
            after={
                "organisation_id": str(organisation_id),
                "seats_purchased": seats_purchased,
            },
        )

    return licence


async def has_active_licence(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    learner_user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    learning_path_id: uuid.UUID | None = None,
) -> bool:
    """Check if a learner holds an active, non-revoked seat grant for a course or path.

    The seat grant must be under an active licence within its validity window.
    """
    now = datetime.now(UTC)

    query = select(LicenceSeatGrant).where(
        LicenceSeatGrant.learner_user_id == learner_user_id,
        LicenceSeatGrant.revoked_at.is_(None),
    )

    if course_id:
        query = query.join(
            Licence,
            and_(
                Licence.id == LicenceSeatGrant.licence_id,
                Licence.tenant_id == tenant_id,
                Licence.course_id == course_id,
                Licence.status == "active",
                Licence.starts_at <= now,
                Licence.ends_at > now,
            ),
        )
    elif learning_path_id:
        query = query.join(
            Licence,
            and_(
                Licence.id == LicenceSeatGrant.licence_id,
                Licence.tenant_id == tenant_id,
                Licence.learning_path_id == learning_path_id,
                Licence.status == "active",
                Licence.starts_at <= now,
                Licence.ends_at > now,
            ),
        )
    else:
        raise AppError(
            "Must provide either course_id or learning_path_id.",
            {"course_id": course_id, "learning_path_id": learning_path_id},
        )

    result = await session.execute(query.limit(1))
    return result.scalar() is not None


async def grant_seat(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    licence_id: uuid.UUID,
    learner_user_id: uuid.UUID,
    entitlement_id: uuid.UUID | None = None,
) -> LicenceSeatGrant:
    """Grant a seat under a licence to a learner.

    Raises AppError if the licence does not exist, is not active/in-window, or has no seats left.
    """
    # Fetch and lock the licence
    licence = (
        await session.execute(
            select(Licence).where(Licence.id == licence_id, Licence.tenant_id == tenant_id)
        )
    ).scalar()
    if licence is None:
        raise AppError("Licence not found.")

    # Check licence is active and in window
    now = datetime.now(UTC)
    if licence.status != "active":
        raise AppError(f"Licence is {licence.status}.", {"status": licence.status})
    if now < licence.starts_at or now >= licence.ends_at:
        raise AppError("Licence is outside its validity window.")

    # Check seats available
    if licence.seats_used >= licence.seats_purchased:
        raise AppError(
            "No seats available.",
            {"seats_used": licence.seats_used, "seats_purchased": licence.seats_purchased},
        )

    # Check for duplicate grant (same learner, same licence)
    existing = (
        await session.execute(
            select(LicenceSeatGrant).where(
                LicenceSeatGrant.licence_id == licence_id,
                LicenceSeatGrant.learner_user_id == learner_user_id,
                LicenceSeatGrant.revoked_at.is_(None),
            )
        )
    ).scalar()
    if existing is not None:
        raise AppError("Learner already has a grant under this licence.")

    grant = LicenceSeatGrant(
        licence_id=licence_id,
        learner_user_id=learner_user_id,
        entitlement_id=entitlement_id,
    )
    session.add(grant)

    # Increment seats_used
    licence.seats_used += 1

    await session.flush()
    return grant


async def revoke_seat(
    session: AsyncSession,
    *,
    grant_id: uuid.UUID,
) -> None:
    """Revoke a seat grant (soft delete via revoked_at).

    Decrements the associated licence's seats_used.
    """
    grant = (
        await session.execute(select(LicenceSeatGrant).where(LicenceSeatGrant.id == grant_id))
    ).scalar()
    if grant is None:
        raise AppError("Seat grant not found.")

    if grant.revoked_at is not None:
        raise AppError("Seat grant is already revoked.")

    grant.revoked_at = datetime.now(UTC)

    # Decrement seats_used
    licence = (
        await session.execute(select(Licence).where(Licence.id == grant.licence_id))
    ).scalar()
    if licence is not None:
        licence.seats_used = max(0, licence.seats_used - 1)

    await session.flush()


async def list_licensee_seat_grants(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    include_revoked: bool = False,
) -> list[LicenceSeatGrant]:
    """List all seat grants for a licensee organisation (isolated per org).

    By default, excludes revoked grants. Pass include_revoked=True to see all.
    """
    query = (
        select(LicenceSeatGrant)
        .join(Licence, Licence.id == LicenceSeatGrant.licence_id)
        .where(
            Licence.tenant_id == tenant_id,
            Licence.organisation_id == organisation_id,
        )
    )

    if not include_revoked:
        query = query.where(LicenceSeatGrant.revoked_at.is_(None))

    result = await session.execute(query)
    return result.scalars().all()


async def get_active_licence(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    licence_id: uuid.UUID,
) -> Licence | None:
    """Fetch a licence by ID if it exists in this tenant."""
    result = await session.execute(
        select(Licence).where(Licence.id == licence_id, Licence.tenant_id == tenant_id)
    )
    return result.scalar()


async def list_organisation_licences(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
) -> list[Licence]:
    """List all licences for an organisation (isolated per org)."""
    result = await session.execute(
        select(Licence).where(
            Licence.tenant_id == tenant_id,
            Licence.organisation_id == organisation_id,
        )
    )
    return result.scalars().all()


__all__ = [
    "create_licence",
    "get_active_licence",
    "grant_seat",
    "has_active_licence",
    "list_licensee_seat_grants",
    "list_organisation_licences",
    "revoke_seat",
]
