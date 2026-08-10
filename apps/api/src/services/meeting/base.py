"""The pluggable meeting-provider contract (REQ-WS-06): Teams first, Zoom
and Meet behind the same interface, manual link as the always-available
fallback. Every provider implements exactly this — nothing in
`services/workshops.py` branches on which provider it's talking to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from src.models.workshop import WorkshopSession


class MeetingProviderUnavailable(Exception):
    """The provider could not provision a meeting — missing credentials,
    an unreachable API, or a genuine outage. Callers fail closed: the
    caller decides whether to fall back to `manual`, never silently
    proceed without a real join link."""


@dataclass(frozen=True, slots=True)
class MeetingDetails:
    provider: str
    provider_meeting_id: str | None
    join_url: str | None


class MeetingProvider(Protocol):
    name: str

    async def create_meeting(
        self, *, session: WorkshopSession, organiser_user_id: uuid.UUID
    ) -> MeetingDetails: ...

    async def cancel_meeting(self, *, provider_meeting_id: str | None) -> None: ...


__all__ = ["MeetingDetails", "MeetingProvider", "MeetingProviderUnavailable"]
