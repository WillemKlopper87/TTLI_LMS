"""`services/meeting/meet.py` (P13 phase 5, REQ-WS-05/06).

Same class of pure unit test as `test_meeting_teams.py`/
`test_meeting_zoom.py`, which this borrows its shape from: a custom
`httpx.AsyncBaseTransport` answering Google's token endpoint and
Calendar event resources, monkeypatched in place of a real connection.
A real (test-only, freshly generated) RSA key pair signs and verifies
the JWT-bearer assertion, so the token-request test is checking a real
signature, not a stub. Genuinely live-testing this needs a Google
Workspace service account with domain-wide delegation nobody has
provisioned in this environment (see the module's own docstring); this
is the achievable bar — assert the exact requests sent and the exact
responses parsed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from src.core.config import Settings
from src.services.meeting import meet
from src.services.meeting.base import MeetingProviderUnavailable
from src.services.meeting.meet import MeetMeetingProvider


def _generate_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


PRIVATE_KEY_PEM = _generate_private_key_pem()


def _settings(**overrides: str) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "google_service_account_email": "ttli-workshops@test-project.iam.gserviceaccount.com",
        "google_service_account_private_key": PRIVATE_KEY_PEM,
        "google_organiser_email": "workshops@ttli.example.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class FakeGoogle(httpx.AsyncBaseTransport):
    """Answers the token endpoint and a single Calendar event resource.
    Anything else 404s, so an unexpected outbound call fails loudly."""

    def __init__(self) -> None:
        self.token_assertions: list[str] = []
        self.token_calls = 0
        self.events: dict[str, dict[str, Any]] = {}
        self.created_bodies: list[dict[str, Any]] = []
        self.deleted_ids: list[str] = []
        self.token_status = 200
        self.force_401_count = 0
        self.auth_headers_seen: list[str] = []
        self._next_id = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == meet.GOOGLE_TOKEN_URL:
            self.token_calls += 1
            form = dict(
                pair.split("=", 1) for pair in request.content.decode().split("&") if "=" in pair
            )
            assert form.get("grant_type") == "urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
            self.token_assertions.append(form["assertion"])
            if self.token_status >= 400:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"fake-google-token-{self.token_calls}",
                    "expires_in": 3600,
                },
            )

        self.auth_headers_seen.append(request.headers.get("authorization", ""))
        if self.force_401_count > 0:
            self.force_401_count -= 1
            return httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})

        if request.method == "POST" and "/events" in url and "/events/" not in url:
            body = json.loads(request.content)
            self.created_bodies.append(body)
            self._next_id += 1
            event_id = f"event{self._next_id}"
            self.events[event_id] = {**body, "id": event_id}
            return httpx.Response(
                200,
                json={
                    "id": event_id,
                    "hangoutLink": f"https://meet.google.com/{event_id}",
                },
            )
        if request.method == "GET" and "/events/" in url:
            event_id = url.rsplit("/", 1)[-1].split("?", 1)[0]
            event = self.events.get(event_id)
            if event is None:
                return httpx.Response(404, json={"error": {"message": "not found"}})
            return httpx.Response(200, json=event)
        if request.method == "PATCH" and "/events/" in url:
            event_id = url.split("/events/", 1)[-1].split("?", 1)[0]
            body = json.loads(request.content)
            self.events.setdefault(event_id, {}).update(body)
            return httpx.Response(200, json=self.events[event_id])
        if request.method == "DELETE" and "/events/" in url:
            event_id = url.split("/events/", 1)[-1].split("?", 1)[0]
            self.deleted_ids.append(event_id)
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def fake_google(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    fake = FakeGoogle()
    real_client = httpx.AsyncClient

    def patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = fake
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meet.httpx, "AsyncClient", patched)
    monkeypatch.setattr(meet, "_cached_token", None)
    monkeypatch.setattr(meet, "_cached_token_expiry", 0.0)
    return fake


class _FakeWorkshopSession:
    starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    ends_at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


async def test_unconfigured_refuses_before_any_http_call(fake_google: FakeGoogle) -> None:
    provider = MeetMeetingProvider(_settings(google_organiser_email=""))
    with pytest.raises(MeetingProviderUnavailable):
        await provider.create_meeting(
            session=_FakeWorkshopSession(),  # type: ignore[arg-type]
            organiser_user_id=uuid.uuid4(),
            attendee_emails=["facilitator@example.com"],
        )
    assert fake_google.token_calls == 0


async def test_a_malformed_private_key_refuses_cleanly_before_any_http_call(
    fake_google: FakeGoogle,
) -> None:
    provider = MeetMeetingProvider(_settings(google_service_account_private_key="not a real key"))
    with pytest.raises(MeetingProviderUnavailable):
        await provider._get_token()
    assert fake_google.token_calls == 0


async def test_token_assertion_carries_the_expected_claims(fake_google: FakeGoogle) -> None:
    provider = MeetMeetingProvider(_settings())
    await provider._get_token()
    assert fake_google.token_calls == 1

    assertion = fake_google.token_assertions[0]
    # A real signature over real claims, verified with the matching
    # public key — not just "some string was sent".
    private_key = serialization.load_pem_private_key(PRIVATE_KEY_PEM.encode(), password=None)
    claims = pyjwt.decode(
        assertion,
        key=private_key.public_key(),
        algorithms=["RS256"],
        audience=meet.GOOGLE_TOKEN_URL,
    )
    assert claims["iss"] == "ttli-workshops@test-project.iam.gserviceaccount.com"
    assert claims["sub"] == "workshops@ttli.example.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/calendar"
    assert claims["aud"] == meet.GOOGLE_TOKEN_URL
    assert claims["exp"] > claims["iat"]


async def test_token_is_cached_across_calls(fake_google: FakeGoogle) -> None:
    provider = MeetMeetingProvider(_settings())
    first = await provider._get_token()
    second = await provider._get_token()
    assert first == second == "fake-google-token-1"
    assert fake_google.token_calls == 1


async def test_bad_credentials_raise_cleanly(fake_google: FakeGoogle) -> None:
    fake_google.token_status = 401
    provider = MeetMeetingProvider(_settings())
    with pytest.raises(MeetingProviderUnavailable):
        await provider._get_token()


async def test_create_meeting_sends_expected_event_body_and_parses_response(
    fake_google: FakeGoogle,
) -> None:
    provider = MeetMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator-a@example.com", "facilitator-b@example.com"],
    )
    assert details.provider == "meet"
    assert details.provider_meeting_id is not None
    assert details.join_url == f"https://meet.google.com/{details.provider_meeting_id}"

    assert len(fake_google.created_bodies) == 1
    body = fake_google.created_bodies[0]
    assert body["start"]["dateTime"] == "2026-09-01T09:00:00+00:00"
    assert body["end"]["dateTime"] == "2026-09-01T10:00:00+00:00"
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"]["type"] == (
        "hangoutsMeet"
    )
    addresses = {a["email"] for a in body["attendees"]}
    assert addresses == {"facilitator-a@example.com", "facilitator-b@example.com"}


async def test_cancel_meeting_deletes_the_event(fake_google: FakeGoogle) -> None:
    provider = MeetMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=[],
    )
    await provider.cancel_meeting(provider_meeting_id=details.provider_meeting_id)
    assert fake_google.deleted_ids == [details.provider_meeting_id]


async def test_cancel_meeting_is_a_noop_with_no_meeting_id(fake_google: FakeGoogle) -> None:
    provider = MeetMeetingProvider(_settings())
    await provider.cancel_meeting(provider_meeting_id=None)
    assert fake_google.deleted_ids == []
    assert fake_google.token_calls == 0


async def test_add_then_remove_attendee_round_trips_through_the_event(
    fake_google: FakeGoogle,
) -> None:
    provider = MeetMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator@example.com"],
    )
    event_id = details.provider_meeting_id
    assert event_id is not None

    await provider.add_attendee(provider_meeting_id=event_id, email="learner@example.com")
    addresses = {a["email"] for a in fake_google.events[event_id]["attendees"]}
    assert addresses == {"facilitator@example.com", "learner@example.com"}

    # Adding the same learner again is a no-op, not a duplicate attendee.
    await provider.add_attendee(provider_meeting_id=event_id, email="learner@example.com")
    assert len(fake_google.events[event_id]["attendees"]) == 2

    await provider.remove_attendee(provider_meeting_id=event_id, email="learner@example.com")
    addresses = {a["email"] for a in fake_google.events[event_id]["attendees"]}
    assert addresses == {"facilitator@example.com"}


async def test_a_stale_cached_token_is_retried_once_with_a_fresh_one(
    fake_google: FakeGoogle,
) -> None:
    provider = MeetMeetingProvider(_settings())
    await provider._get_token()
    assert fake_google.token_calls == 1

    fake_google.force_401_count = 1
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator@example.com"],
    )
    assert details.provider_meeting_id is not None
    assert fake_google.token_calls == 2
    assert fake_google.auth_headers_seen == [
        "Bearer fake-google-token-1",
        "Bearer fake-google-token-2",
    ]
    await provider.cancel_meeting(provider_meeting_id=details.provider_meeting_id)
    assert fake_google.token_calls == 2


async def test_two_consecutive_401s_still_raise_cleanly(fake_google: FakeGoogle) -> None:
    provider = MeetMeetingProvider(_settings())
    fake_google.force_401_count = 2
    with pytest.raises(MeetingProviderUnavailable):
        await provider.create_meeting(
            session=_FakeWorkshopSession(),  # type: ignore[arg-type]
            organiser_user_id=uuid.uuid4(),
            attendee_emails=[],
        )
    assert fake_google.token_calls == 2
