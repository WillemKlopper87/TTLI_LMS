"""Google Meet via a Workspace service account + the Calendar API v3
(REQ-WS-05/06, P13 phase 5 — mirrors `services/meeting/teams.py` and
`services/meeting/zoom.py`'s exact rigor and disclosure pattern).

**A calendar event with `conferenceData.createRequest`, not a bare
Meet-only resource** — same reasoning as the Teams provider's own
docstring: Google Calendar's `events.insert` with
`conferenceData.createRequest{conferenceSolutionKey.type:
"hangoutsMeet"}` both provisions the Meet call *and* emails a real
Calendar invite to every attendee (`sendUpdates=all`), `events.patch`
updates it (used here to add/remove one learner as they book/cancel),
and `events.delete` cancels it — Calendar sends the cancellation email
on our behalf. One Graph-shaped resource for all four REQ-WS-05 verbs,
exactly like Teams.

**Domain-wide delegation, not per-facilitator OAuth** — a service
account's own identity cannot create Workspace calendar events or send
real invites; it must impersonate a real Workspace user via domain-
wide delegation (the JWT-bearer flow's `sub` claim). `Settings.
google_organiser_email` is that one impersonated user, platform-wide —
same one-service-identity design `graph_organiser_upn`/
`zoom_organiser_email` already use, and for the same reason: no per-
facilitator Workspace licence or delegated scope is needed. A
facilitator is listed as an *attendee*, never the impersonated
organiser.

**No new dependency for the JWT-bearer assertion** — `PyJWT` (with its
`cryptography` backend) is already a dependency, used elsewhere in
this codebase for this service's own access/refresh tokens
(`core/security.py`) and to verify an IdP's OIDC tokens
(`services/oidc.py`). Google's JWT-bearer flow just needs the same
library's RS256 *signing* path instead of HS256/verification — not a
new library, the same one used one algorithm differently.

**Not live-verifiable in this environment**: no Google Workspace
service account with domain-wide delegation has been provisioned here
(`core/config.py`'s `google_*` fields are all empty by default).
`is_configured()` refuses cleanly before ever attempting a call.
Unit-tested against `httpx` mocked at the transport level; genuinely
live-tested only once a tenant provisions real credentials — flagged
the same way in `docs/STATUS.md` as Teams and Zoom already are.
"""

from __future__ import annotations

import time
import uuid

import httpx
import jwt

from src.core.config import Settings
from src.models.workshop import WorkshopSession
from src.services.meeting.base import MeetingDetails, MeetingProviderUnavailable

GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
JWT_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
JWT_ASSERTION_LIFETIME_SECONDS = 3600
REQUEST_TIMEOUT = 10.0
TOKEN_EXPIRY_SKEW_SECONDS = 60

# Module-level for the same reason teams.py's/zoom.py's caches are:
# Settings (and so the token) is platform-wide, not per-tenant, and
# get_provider() builds a fresh MeetMeetingProvider on every call.
_cached_token: str | None = None
_cached_token_expiry: float = 0.0


class MeetMeetingProvider:
    name = "meet"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(
            self._settings.google_service_account_email
            and self._settings.google_service_account_private_key
            and self._settings.google_organiser_email
        )

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise MeetingProviderUnavailable(
                "Google Meet is not configured — GOOGLE_SERVICE_ACCOUNT_EMAIL/"
                "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY/GOOGLE_ORGANISER_EMAIL are not all set. "
                "Use the manual provider until a Workspace service account with domain-wide "
                "delegation exists."
            )

    def _signed_assertion(self) -> str:
        now = int(time.time())
        claims = {
            "iss": self._settings.google_service_account_email,
            "scope": GOOGLE_CALENDAR_SCOPE,
            "aud": GOOGLE_TOKEN_URL,
            "iat": now,
            "exp": now + JWT_ASSERTION_LIFETIME_SECONDS,
            # Domain-wide delegation: the service account has no calendar
            # of its own — this is what makes the resulting token act as
            # google_organiser_email, not the service account itself.
            "sub": self._settings.google_organiser_email,
        }
        return jwt.encode(
            claims, self._settings.google_service_account_private_key, algorithm="RS256"
        )

    async def _get_token(self) -> str:
        global _cached_token, _cached_token_expiry
        now = time.monotonic()
        if _cached_token is not None and now < _cached_token_expiry:
            return _cached_token

        try:
            assertion = self._signed_assertion()
        except (jwt.PyJWTError, ValueError) as exc:
            raise MeetingProviderUnavailable(
                "Could not sign a Google JWT-bearer assertion — check "
                "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY is a valid PEM private key."
            ) from exc

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={"grant_type": JWT_GRANT_TYPE, "assertion": assertion},
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise MeetingProviderUnavailable("Google could not be reached.") from exc

        if response.status_code >= 400:
            raise MeetingProviderUnavailable(
                "Google rejected this service account — check the Workspace admin console's "
                "domain-wide delegation is authorised for the Calendar scope."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str):
            raise MeetingProviderUnavailable("Google returned no access token.")

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
                    f"{GOOGLE_API_BASE}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise MeetingProviderUnavailable("Google could not be reached.") from exc

    async def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> httpx.Response:
        global _cached_token, _cached_token_expiry
        token = await self._get_token()
        response = await self._send(method, path, token=token, json=json)
        if response.status_code == 401:
            # Same recovery as teams.py/zoom.py's _request: a service
            # account key rotated in the Workspace admin console mid-
            # lifetime would otherwise fail every call until the cached
            # token's clock runs out. Drop the cache and retry once.
            _cached_token = None
            _cached_token_expiry = 0.0
            token = await self._get_token()
            response = await self._send(method, path, token=token, json=json)
        if response.status_code >= 400:
            raise MeetingProviderUnavailable(
                f"Google rejected this request ({response.status_code})."
            )
        return response

    async def create_meeting(
        self, *, session: WorkshopSession, organiser_user_id: uuid.UUID, attendee_emails: list[str]
    ) -> MeetingDetails:
        self._require_configured()
        body: dict[str, object] = {
            "summary": "TTLI workshop session",
            "start": {"dateTime": session.starts_at.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": session.ends_at.isoformat(), "timeZone": "UTC"},
            "attendees": [{"email": email} for email in attendee_emails],
            "conferenceData": {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        response = await self._request(
            "POST",
            "/calendars/primary/events?conferenceDataVersion=1&sendUpdates=all",
            json=body,
        )
        payload = response.json()
        event_id = payload.get("id")
        join_url = payload.get("hangoutLink")
        if not isinstance(event_id, str):
            raise MeetingProviderUnavailable("Google returned no event id.")
        return MeetingDetails(
            provider=self.name,
            provider_meeting_id=event_id,
            join_url=join_url if isinstance(join_url, str) else None,
        )

    async def cancel_meeting(self, *, provider_meeting_id: str | None) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        await self._request(
            "DELETE", f"/calendars/primary/events/{provider_meeting_id}?sendUpdates=all"
        )
        return None

    async def _patch_attendees(
        self, *, provider_meeting_id: str, attendees: list[dict[str, object]]
    ) -> None:
        # Same GET-mutate-PATCH non-atomicity disclosed in teams.py's
        # _patch_attendees (overall-review F8): two truly concurrent
        # calls against the *same* event can interleave. Two concurrent
        # *bookings* of the same session are already serialised by
        # book_session's row lock, so that specific race can't happen;
        # a booking racing a cancellation on the same session is not
        # locked against this method — left open, same as Teams, for a
        # low-severity race against a provider nothing live-configures.
        await self._request(
            "PATCH",
            f"/calendars/primary/events/{provider_meeting_id}?sendUpdates=all",
            json={"attendees": attendees},
        )

    async def add_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        current = await self._request("GET", f"/calendars/primary/events/{provider_meeting_id}")
        attendees = current.json().get("attendees") or []
        addresses = {a.get("email", "").lower() for a in attendees}
        if email.lower() in addresses:
            return None
        attendees.append({"email": email})
        await self._patch_attendees(provider_meeting_id=provider_meeting_id, attendees=attendees)

    async def remove_attendee(self, *, provider_meeting_id: str | None, email: str) -> None:
        if not self.is_configured() or provider_meeting_id is None:
            return None
        current = await self._request("GET", f"/calendars/primary/events/{provider_meeting_id}")
        attendees = current.json().get("attendees") or []
        target = email.lower()
        remaining = [a for a in attendees if a.get("email", "").lower() != target]
        if len(remaining) == len(attendees):
            return None
        await self._patch_attendees(provider_meeting_id=provider_meeting_id, attendees=remaining)


__all__ = ["MeetMeetingProvider"]
