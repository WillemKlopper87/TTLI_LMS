"""The bridge between commerce and learning (02 §4.7).

Granted only on an order's transition to `fulfilled`, and never before
(02 §6.2). `target_id` is polymorphic on `kind` (no FK — see the model's
own docstring); for `kind="course"` it is the real `courses.id` (Phase 4),
resolved from `Product.course_id` by the caller
(services/orders.py::approve_eft), not the product's own id used as a
stand-in before courses existed.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.models.commerce import Entitlement


async def grant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_order_id: uuid.UUID,
    kind: str,
    target_id: uuid.UUID,
    quantity: int | None = None,
) -> Entitlement:
    entitlement = Entitlement(
        id=uuid7(),
        tenant_id=tenant_id,
        user_id=user_id,
        source_order_id=source_order_id,
        kind=kind,
        target_id=target_id,
        quantity=quantity,
    )
    session.add(entitlement)
    await session.flush()
    return entitlement


__all__ = ["grant"]
