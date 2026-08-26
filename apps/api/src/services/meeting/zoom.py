"""Zoom via Server-to-Server OAuth + the REST API v2 (REQ-WS-05/06,
P13 phase 4 — mirrors `services/meeting/teams.py`'s exact rigor and
disclosure pattern).

**Server-to-Server OAuth**, not the older JWT app type Zoom deprecated:
`POST https://zoom.us/oauth/token?grant_type=account_credentials
&account_id={ZOOM_ACCOUNT_ID}` with HTTP Basic auth
(`client_id:client_secret`) — no user ever approves a consent screen,
same "app credentials, no human in the loop" shape `services/oidc.py`
and `services/meeting/teams.py` both already use, just with Zoom's own
request format (query string + Basic auth, not a form body).

**One service Zoom user, not one per facilitator** — same reasoning as
`Settings.graph_organiser_upn`: `Settings.zoom_organiser_email` hosts
every workshop's meeting, so no per-facilitator Zoom Pro licence is
ever needed. Zoom meetings have no single "attendees" list the way a
Graph calendar event does, so this maps to two different Zoom
mechanisms instead of one:

- **Facilitators → `settings.alternative_hosts`** (a comma-separated
  string of Zoom user emails), set once at creation — they need host-
  level controls (mute, spotlight, end meeting), not just a join link.
- **Learners → meeting registrants**, added/removed one at a time as
  `services/workshops.py::book_session`/`_cancel_booking_row` call
  `add_attendee`/`remove_attendee`, via Zoom's Meeting Registrants API
  (`POST/PUT .../registrants*`) — the same per-booking invite pattern
  Teams' `_patch_attendees` uses, just against a different Zoom
  resource shape. Zoom's registrant-create endpoint requires a
  `first_name`, which `add_attendee`'s contract (an email, matching
  the shared `MeetingProvider` Protocol) doesn't carry — derived from
  the local part of the email address rather than widening the
  Protocol for one provider's quirk.

**No new dependency** — `httpx` only, same reasoning as `teams.py`.

**Not live-verifiable in this environment**: no Zoom Server-to-Server
OAuth app has been provisioned here (`core/config.py`'s `zoom_*`
fields are all empty by default). `is_configured()` refuses cleanly
before ever attempting a call. Unit-tested against `httpx` mocked at
the transport level; genuinely live-tested only once a tenant
provisions real credentials — flagged the same way in `docs/STATUS.md`
as Teams already is.
"""

from __future__ import annotations

import base64
import time
import uuid

import httpx

from src.core.config import Settings
from src.models.workshop import WorkshopSession
from src.services.meeting.base import MeetingDetails, MeetingProviderUnavailable

ZOOM_API_BASE = "https://api.zoom.us/v2"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"  # noqa: S105 - a URL, not a secret
REQUEST_TIMEOUT = 10.0
TOKEN_EXPIRY_SKEW_SECONDS = 60

# Module-level for the same reason teams.py's cache is: Settings (and so
# the token) is platform-wide, not per-tenant, and get_provider() builds
# a fresh ZoomMeetingProvider on every call.
_cached_token: str | None = None
_cached_token_expiry: float = 0.0


class ZoomMeetingProvider:
    name = "zoom"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(
            self._settings.zoom_account_id
            and self._settings.zoom_client_id
            and self._settings.zoom_client_secret
            and self._settings.zoom_organiser_email
        )

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise MeetingProviderUnavailable(
                "Zoom is not configured — ZOOM_ACCOUNT_ID/ZOOM_CLIENT_ID/ZOOM_CLIENT_SECRET/"
                "ZOOM_ORGANISER_EMAIL are not all set. Use the manual provider until a "
                "Server-to-Server OAuth app exists."
            )

    async def _get_token(self) -> str:
        global _cached_token, _cached_token_expiry
        now = time.monotonic()
        if _cached_token is not None and now < _cached_token_expiry:
            return _cached_token

        basic = base64.b64encode(
            f"{self._settings.zoom_client_id}:{self._settings.zoom_client_secret}".encode()
        ).decode()
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    ZOOM_TOKEN_URL,
                    params={
                        "grant_type": "account_credentials",
                        "account_id": self._settings.zoom_account_id,
                    },
                    headers={"Authorization": f"Basic {basic}", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise MeetingProviderUnavailable("Zoom could not be reached.") from exc

        if response.status_code >= 400:
            raise MeetingProviderUnavailable(
                "Zoom rejected these credentials — check the Server-to-Server OAuth app's "
                "account id, client id and client secret."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str):
            raise MeetingProviderUnavailable("Zoom returned no access token.")

        expires_in = payload.get("expires_in")
        ttl = float(expires_in) if isinstance(expires_in, int | float) else 0.0
        _cached_token = token
        _cached_token_expiry = now + max(ttl - TOKEN_EXPIRY_SKEW_SECONDS, 0.0)
        return token

    async def _send(
        self, method: str, path: str, *, token: str, json: dict[str, object] | None = None
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                return await client.request(
                    method,
                    f"{ZOOM_API_BASE}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise MeetingProviderUnavailable("Zoom could not be reached.") from exc

    async def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> httpx.Response:
        global _cached_token, _cached_token_expiry
        token = await self._get_token()
        response = await self._send(method, path, token=token, json=json)
        if response.status_code == 401:
            # Same recovery as teams.py::_request F9: a client secret
            # rotated in the Zoom marketplace app mid-lifetime would
            # otherwise fail every call until the cached token's clock
            # runs out. Drop the cache and retry once with a fresh token.
            _cached_token = None
            _cached_token_expiry = 0.0
            token = await self._get_token()
            response = await self._send(method, path, token=token, json=json)
        if response.status_code >= 400:
            raise MeetingProviderUnavailable(
                f"Zoom rejected this request ({response.status_code})."
            )
        return response

    async def create_meeting(
        self, *, session: WorkshopSession, organiser_user_id: uuid.UUID, attendee_emails: list[str]
    ) -> MeetingDetails:
        self._require_configured()
        duration_minutes = max(1, round((session.ends_at - session.starts_at).total_seconds() / 60))
        meeting_settings: dict[str, object] = {
            "approval_type": 0,  # auto-approve registrants
            "join_before_host": False,
        }
        if attendee_emails:
            meeting_settings["alternative_hosts"] = ",".join(attendee_emails)
        body: dict[str, object] = {
            "topic": "TTLI workshop session",
            "type": 2,  # scheduled meeting
            "start_time": session.starts_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration": duration_minutes,
            "timezone": "UTC",
            "settings": meeting_settings,
        }

        response = await self._request(
            "POST", f"/users/{self._settings.zoom_organiser_email}/meetings", json=body
        )
        payload = response.json()
        meeting_id = payload.get("id")
        join_url = payload.get("join_url")
        if meeting_id is None:
            raise MeetingProviderUnavailable("Zoom returned no meeting id.")
        return MeetingDetails(
            provider=self.name,
            provider_meeting_id=str(meeting_id),
            join_url=join_url if isinstance(join_url, str) else None,
        )

    async def cancel_meeting(self, *, provider_meeting_id: str | None) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        await self._request("DELETE", f"/meetings/{provider_meeting_id}")
        return None

    def _registrant_name(self, email: str) -> str:
        local_part = email.split("@", 1)[0]
        return local_part.replace(".", " ").replace("_", " ").title() or "Learner"

    async def add_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        current = await self._request(
            "GET", f"/meetings/{provider_meeting_id}/registrants?status=approved"
        )
        registrants = current.json().get("registrants") or []
        if any(r.get("email", "").lower() == email.lower() for r in registrants):
            return None
        await self._request(
            "POST",
            f"/meetings/{provider_meeting_id}/registrants",
            json={"email": email, "first_name": self._registrant_name(email)},
        )

    async def remove_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        current = await self._request(
            "GET", f"/meetings/{provider_meeting_id}/registrants?status=approved"
        )
        registrants = current.json().get("registrants") or []
        if not any(r.get("email", "").lower() == email.lower() for r in registrants):
            return None
        await self._request(
            "PUT",
            f"/meetings/{provider_meeting_id}/registrants/status",
            json={"action": "cancel", "registrants": [{"email": email}]},
        )


__all__ = ["ZoomMeetingProvider"]
