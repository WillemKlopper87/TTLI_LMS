"""Writing consent records (04 §5.1).

One append-only row per consent event — never an update to a prior one, even
a withdrawal. Deliberately narrow, same shape as services/audit.py: one
function, no update path, because the table refuses UPDATE and DELETE at the
database level (0007) so there is nothing else to offer.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.consent import ConsentRecord

Purpose = Literal["marketing", "analytics", "ai_processing"]


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    purpose: Purpose,
    granted: bool,
    source: str,
    policy_version: str,
    user_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> None:
    if (user_id is None) == (contact_id is None):
        raise ValueError("exactly one of user_id or contact_id must be set")
    session.add(
        ConsentRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            contact_id=contact_id,
            purpose=purpose,
            granted=granted,
            source=source,
            policy_version=policy_version,
            ip=ip,
        )
    )
    await session.flush()


__all__ = ["Purpose", "record"]
