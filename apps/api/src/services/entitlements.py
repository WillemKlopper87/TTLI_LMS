"""The bridge between commerce and learning (02 §4.7).

Granted only on an order's transition to `fulfilled`, and never before
(02 §6.2) — the course/learning-path tables `target_id` would eventually
point at don't exist yet (Phase 4), so today's only `kind` is `course`,
carrying the product's own id as a stand-in target until that phase gives
it a real one.
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
