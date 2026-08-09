"""Writing first-party analytics events (02 §11.1) — the table has existed
since Sprint 3 with nothing writing to it; this is that write path.

`consent_marketing` is always False here: nothing in this module fires from
a marketing surface. `consent_analytics` defaults True for the
operational/security events this module currently emits (login, token
refresh, lead capture) — first-party, necessary-for-the-service telemetry,
which 04 §5.1 allows to "run in anonymous mode without consent, since
first-party events with no identifier attached are not personal
information." These events *do* carry `user_id` when authenticated, so that
reasoning is stretched, not a clean fit — revisit once real consent-capture
UI exists (the Phase 2 cookie banner) and thread the visitor's actual
recorded preference through instead of this default.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.models.event import Event


class EventName:
    LOGIN_SUCCEEDED = "auth.login.succeeded"
    LOGIN_FAILED = "auth.login.failed"
    MAGIC_LINK_REQUESTED = "auth.magic_link.requested"
    PASSWORD_RESET_REQUESTED = "auth.password_reset.requested"  # noqa: S105 - ditto
    TOKEN_REUSE_DETECTED = "auth.token.reuse_detected"  # noqa: S105 - ditto
    LEAD_CAPTURED = "lead.captured"
    GUEST_ACCESS_GRANTED = "lead.guest_access_granted"


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_name: str,
    anonymous_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    properties: dict[str, Any] | None = None,
    consent_marketing: bool = False,
    consent_analytics: bool = True,
) -> None:
    session.add(
        Event(
            id=uuid7(),
            tenant_id=tenant_id,
            anonymous_id=anonymous_id or uuid7(),
            user_id=user_id,
            session_id=session_id,
            event_name=event_name,
            event_properties=properties or {},
            consent_marketing=consent_marketing,
            consent_analytics=consent_analytics,
        )
    )
    await session.flush()


__all__ = ["EventName", "record"]
