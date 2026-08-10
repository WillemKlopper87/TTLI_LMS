"""Microsoft Teams via Graph API (REQ-WS-05) — structured correctly, but
genuinely blocked on external credentials nobody has provisioned yet
(no Azure AD app registration exists — 01 §1.4's open-decisions class of
gap, not an engineering shortcut). `create_meeting` refuses cleanly
before attempting a call the tenant was never configured to make, the
same fail-closed discipline `services/antivirus.py` uses for an
unreachable scanner — never a fabricated join link pretending Graph
succeeded.
"""

from __future__ import annotations

import uuid

from src.core.config import Settings
from src.models.workshop import WorkshopSession
from src.services.meeting.base import MeetingDetails, MeetingProviderUnavailable


class TeamsMeetingProvider:
    name = "teams"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _configured(self) -> bool:
        return bool(
            self._settings.graph_client_id
            and self._settings.graph_client_secret
            and self._settings.graph_tenant_id
        )

    async def create_meeting(
        self, *, session: WorkshopSession, organiser_user_id: uuid.UUID
    ) -> MeetingDetails:
        if not self._configured():
            raise MeetingProviderUnavailable(
                "Microsoft Teams is not configured — GRAPH_CLIENT_ID/GRAPH_CLIENT_SECRET/"
                "GRAPH_TENANT_ID are not set. Use the manual provider until an Azure AD app "
                "registration exists."
            )
        # A real implementation calls Graph's
        # POST /users/{organiser}/onlineMeetings here. Never reached
        # without real credentials — see the module docstring.
        raise MeetingProviderUnavailable(  # pragma: no cover - unreachable while unconfigured
            "Microsoft Teams integration is not yet implemented."
        )

    async def cancel_meeting(self, *, provider_meeting_id: str | None) -> None:
        if not self._configured() or provider_meeting_id is None:
            return None
        raise MeetingProviderUnavailable(  # pragma: no cover - unreachable while unconfigured
            "Microsoft Teams integration is not yet implemented."
        )


__all__ = ["TeamsMeetingProvider"]
