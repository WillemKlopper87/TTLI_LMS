"""The always-available fallback (02 §9): no automated provisioning, so
nothing here can fail the way a real API call can. `join_url` starts
`None` — the facilitator supplies it by hand — which is what makes a
Teams/Zoom/Meet outage non-blocking (REQ-WS-06's own reasoning).
"""

from __future__ import annotations

import uuid

from src.models.workshop import WorkshopSession
from src.services.meeting.base import MeetingDetails


class ManualMeetingProvider:
    name = "manual"

    async def create_meeting(
        self, *, session: WorkshopSession, organiser_user_id: uuid.UUID, attendee_emails: list[str]
    ) -> MeetingDetails:
        return MeetingDetails(provider=self.name, provider_meeting_id=None, join_url=None)

    async def cancel_meeting(self, *, provider_meeting_id: str | None) -> None:
        return None

    async def add_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        return None

    async def remove_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        return None


__all__ = ["ManualMeetingProvider"]
