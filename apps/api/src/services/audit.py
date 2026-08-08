"""Writing audit events.

Deliberately narrow: one function, no update path. The table refuses UPDATE and
DELETE at the database level, so there is nothing else to offer.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit import AuditEvent


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            action=action,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            ip=ip,
            user_agent=user_agent,
        )
    )
    await session.flush()


__all__ = ["record"]
