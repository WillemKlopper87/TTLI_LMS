"""The bridge between commerce and learning (02 §4.7).

Granted only on an order's transition to `fulfilled`, and never before
(02 §6.2). `target_id` is polymorphic on `kind` (no FK — see the model's
own docstring); for `kind="course"` it is the real `courses.id` (Phase 4),
resolved from `Product.course_id` by the caller
(services/orders.py::approve_eft), not the product's own id used as a
stand-in before courses existed.

`user_id` is nullable (02 §4.7: "organisation-level entitlements exist
before seat assignment") — an organisation's seat purchase grants a
pool entitlement with `user_id=None`, and `services/organisations.py::
assign_seat` grants a second, `user_id`-set entitlement per employee,
drawn from it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.models.commerce import Entitlement


async def grant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    source_order_id: uuid.UUID,
    kind: str,
    target_id: uuid.UUID,
    quantity: int | None = None,
    expires_at: datetime | None = None,
) -> Entitlement:
    entitlement = Entitlement(
        id=uuid7(),
        tenant_id=tenant_id,
        user_id=user_id,
        source_order_id=source_order_id,
        kind=kind,
        target_id=target_id,
        quantity=quantity,
        expires_at=expires_at,
    )
    session.add(entitlement)
    await session.flush()
    return entitlement


async def has_valid_course_entitlement(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> bool:
    """True if the learner holds at least one course entitlement that is
    neither revoked nor (if time-bound) expired. One-time-purchase
    entitlements never set `expires_at`, so they always pass here — this
    only ever restricts access for a *lapsed subscription*
    (services/subscriptions.py), never a one-time course purchase."""
    now = datetime.now(UTC)
    stmt = select(Entitlement.id).where(
        Entitlement.tenant_id == tenant_id,
        Entitlement.user_id == user_id,
        Entitlement.kind == "course",
        Entitlement.target_id == course_id,
        Entitlement.revoked_at.is_(None),
        (Entitlement.expires_at.is_(None)) | (Entitlement.expires_at > now),
    )
    return (await session.execute(stmt)).first() is not None


__all__ = ["grant", "has_valid_course_entitlement"]
