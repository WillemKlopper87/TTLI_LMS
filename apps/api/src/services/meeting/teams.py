"""Microsoft Teams via Graph API (REQ-WS-05/06).

**A calendar event, not the bare `onlineMeetings` resource.** The
backlog's shorthand is "Teams `onlineMeetings` create/cancel", but
REQ-WS-05's full text is "create meeting, generate join link, send
calendar invite, update and cancel." `onlineMeetings` has no
cancel/update primitive and sends no invite. `POST .../events` with
`isOnlineMeeting: true` satisfies all four in one Graph resource: it
both creates the Teams meeting *and* emails real Outlook invites to
every attendee, `PATCH` updates it (used here to add/remove one
learner as they book/cancel), and `DELETE` cancels it — Graph sends
the cancellation email on our behalf.

**One service mailbox, not one per facilitator.** `Settings.
graph_organiser_upn` is the technical organiser for every workshop
across every tenant on this platform (config is platform-wide, not
per-tenant — the same class of blocked-on-external-credentials gap as
Payfast/Netcash, see `core/config.py`). A facilitator is listed as an
*attendee*, never the organiser, so no per-facilitator M365 licence or
delegated Graph permission is ever needed.

**No new dependency** — `httpx` only, mirroring `services/oidc.py::
exchange`'s exact client-credentials/try-except-`httpx.HTTPError`/
clean-4xx-refusal shape. This codebase has consistently declined a
library it would use one function of.

**Not live-verifiable in this environment**: no Azure AD app
registration exists here (`core/config.py`'s `graph_*` fields are all
empty by default). `is_configured()` refuses cleanly before ever
attempting a call, the same fail-closed discipline `services/
antivirus.py` uses for an unreachable scanner. Unit-tested against
`httpx` mocked at the transport level; genuinely live-tested only once
a tenant provisions real credentials.
"""

from __future__ import annotations

import time
import uuid

import httpx

from src.core.config import Settings
from src.models.workshop import WorkshopSession
from src.services.meeting.base import MeetingDetails, MeetingProviderUnavailable

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
REQUEST_TIMEOUT = 10.0
# A cushion against a token that expires mid-flight between the cache
# check and the request it was fetched for.
TOKEN_EXPIRY_SKEW_SECONDS = 60

# Module-level, not per-instance: `get_provider()` builds a fresh
# `TeamsMeetingProvider` on every call, so an instance-level cache would
# never actually be reused. Settings (and so the token) are platform-
# wide, not per-tenant, so one shared entry is correct, not a leak
# across tenants.
_cached_token: str | None = None
_cached_token_expiry: float = 0.0


class TeamsMeetingProvider:
    name = "teams"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(
            self._settings.graph_client_id
            and self._settings.graph_client_secret
            and self._settings.graph_tenant_id
            and self._settings.graph_organiser_upn
        )

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise MeetingProviderUnavailable(
                "Microsoft Teams is not configured — GRAPH_CLIENT_ID/GRAPH_CLIENT_SECRET/"
                "GRAPH_TENANT_ID/GRAPH_ORGANISER_UPN are not all set. Use the manual provider "
                "until an Azure AD app registration exists."
            )

    async def _get_token(self) -> str:
        global _cached_token, _cached_token_expiry
        now = time.monotonic()
        if _cached_token is not None and now < _cached_token_expiry:
            return _cached_token

        url = (
            f"https://login.microsoftonline.com/{self._settings.graph_tenant_id}/oauth2/v2.0/token"
        )
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._settings.graph_client_id,
                        "client_secret": self._settings.graph_client_secret,
                        "scope": "https://graph.microsoft.com/.default",
                    },
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise MeetingProviderUnavailable("Microsoft Graph could not be reached.") from exc

        if response.status_code >= 400:
            raise MeetingProviderUnavailable(
                "Microsoft Graph rejected these credentials — check the Azure AD app "
                "registration's client secret and tenant."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str):
            raise MeetingProviderUnavailable("Microsoft Graph returned no access token.")

        expires_in = payload.get("expires_in")
        ttl = float(expires_in) if isinstance(expires_in, int | float) else 0.0
        _cached_token = token
        _cached_token_expiry = now + max(ttl - TOKEN_EXPIRY_SKEW_SECONDS, 0.0)
        return token

    async def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> httpx.Response:
        token = await self._get_token()
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.request(
                    method,
                    f"{GRAPH_BASE}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise MeetingProviderUnavailable("Microsoft Graph could not be reached.") from exc
        if response.status_code >= 400:
            raise MeetingProviderUnavailable(
                f"Microsoft Graph rejected this request ({response.status_code})."
            )
        return response

    async def create_meeting(
        self, *, session: WorkshopSession, organiser_user_id: uuid.UUID, attendee_emails: list[str]
    ) -> MeetingDetails:
        self._require_configured()
        body = {
            "subject": "TTLI workshop session",
            "start": {"dateTime": session.starts_at.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": session.ends_at.isoformat(), "timeZone": "UTC"},
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
            "attendees": [
                {"emailAddress": {"address": email}, "type": "required"}
                for email in attendee_emails
            ],
        }
        response = await self._request(
            "POST", f"/users/{self._settings.graph_organiser_upn}/events", json=body
        )
        payload = response.json()
        event_id = payload.get("id")
        join_url = (payload.get("onlineMeeting") or {}).get("joinUrl")
        if not isinstance(event_id, str):
            raise MeetingProviderUnavailable("Microsoft Graph returned no event id.")
        return MeetingDetails(
            provider=self.name,
            provider_meeting_id=event_id,
            join_url=join_url if isinstance(join_url, str) else None,
        )

    async def cancel_meeting(self, *, provider_meeting_id: str | None) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        await self._request(
            "DELETE", f"/users/{self._settings.graph_organiser_upn}/events/{provider_meeting_id}"
        )
        return None

    async def _patch_attendees(
        self, *, provider_meeting_id: str, attendees: list[dict[str, object]]
    ) -> None:
        await self._request(
            "PATCH",
            f"/users/{self._settings.graph_organiser_upn}/events/{provider_meeting_id}",
            json={"attendees": attendees},
        )

    async def add_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        current = await self._request(
            "GET", f"/users/{self._settings.graph_organiser_upn}/events/{provider_meeting_id}"
        )
        attendees = current.json().get("attendees") or []
        addresses = {(a.get("emailAddress") or {}).get("address", "").lower() for a in attendees}
        if email.lower() in addresses:
            return None
        attendees.append({"emailAddress": {"address": email}, "type": "required"})
        await self._patch_attendees(provider_meeting_id=provider_meeting_id, attendees=attendees)

    async def remove_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        current = await self._request(
            "GET", f"/users/{self._settings.graph_organiser_upn}/events/{provider_meeting_id}"
        )
        attendees = current.json().get("attendees") or []
        target = email.lower()
        remaining = [
            a
            for a in attendees
            if (a.get("emailAddress") or {}).get("address", "").lower() != target
        ]
        if len(remaining) == len(attendees):
            return None
        await self._patch_attendees(provider_meeting_id=provider_meeting_id, attendees=remaining)


__all__ = ["TeamsMeetingProvider"]
