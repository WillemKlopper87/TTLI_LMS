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
        self, *, session: WorkshopSession, organiser_user_id: uuid.UUID, attendee_emails: list[str]
    ) -> MeetingDetails: ...

    async def cancel_meeting(self, *, provider_meeting_id: str | None) -> None: ...

    # P7 phase 5: a session's meeting is created once (on its first
    # registered booking) with only its facilitator(s) as attendees —
    # nobody's booked yet. Each learner who then registers or cancels is
    # added/removed one at a time as `services/workshops.py::book_session`
    # / `_cancel_booking_row` call these, which is how a real join-link
    # invite (REQ-WS-05) reaches every registrant, not just the
    # facilitator. A no-op for providers with no attendee list to manage.
    async def add_attendee(self, *, provider_meeting_id: str | None, email: str) -> None: ...

    async def remove_attendee(self, *, provider_meeting_id: str | None, email: str) -> None: ...


__all__ = ["MeetingDetails", "MeetingProvider", "MeetingProviderUnavailable"]
