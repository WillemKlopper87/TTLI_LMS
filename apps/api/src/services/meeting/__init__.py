from __future__ import annotations

from src.core.config import Settings
from src.core.errors import AppError
from src.services.meeting.base import MeetingDetails, MeetingProvider, MeetingProviderUnavailable
from src.services.meeting.manual import ManualMeetingProvider
from src.services.meeting.teams import TeamsMeetingProvider
from src.services.meeting.zoom import ZoomMeetingProvider


def get_provider(name: str, *, settings: Settings) -> MeetingProvider:
    if name == "manual":
        return ManualMeetingProvider()
    if name == "teams":
        return TeamsMeetingProvider(settings)
    if name == "zoom":
        return ZoomMeetingProvider(settings)
    raise AppError(f"Unknown meeting provider: {name}")


__all__ = [
    "MeetingDetails",
    "MeetingProvider",
    "MeetingProviderUnavailable",
    "get_provider",
]
