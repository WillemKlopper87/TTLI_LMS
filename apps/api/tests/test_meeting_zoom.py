"""`services/meeting/zoom.py` (P13 phase 4, REQ-WS-05/06).

Same class of pure unit test as `test_meeting_teams.py`, which this
borrows its shape from: a custom `httpx.AsyncBaseTransport` answering
Zoom's token endpoint and meeting/registrant resources, monkeypatched
in place of a real connection. Genuinely live-testing this needs a
Zoom Server-to-Server OAuth app nobody has provisioned in this
environment (see the module's own docstring); this is the achievable
bar — assert the exact requests sent and the exact responses parsed.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from src.core.config import Settings
from src.services.meeting import zoom
from src.services.meeting.base import MeetingProviderUnavailable
from src.services.meeting.zoom import ZoomMeetingProvider


def _settings(**overrides: str) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "zoom_account_id": "test-account-id",
        "zoom_client_id": "test-client-id",
        "zoom_client_secret": "test-client-secret",
        "zoom_organiser_email": "workshops@ttli.example.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class FakeZoom(httpx.AsyncBaseTransport):
    """Answers the token endpoint and a single meeting resource plus its
    registrants. Anything else 404s, so an unexpected outbound call fails
    loudly."""

    def __init__(self) -> None:
        self.token_requests: list[dict[str, str]] = []
        self.token_calls = 0
        self.meetings: dict[str, dict[str, Any]] = {}
        self.registrants: dict[str, list[dict[str, str]]] = {}
        self.created_bodies: list[dict[str, Any]] = []
        self.deleted_ids: list[str] = []
        self.token_status = 200
        self.force_401_count = 0
        self.auth_headers_seen: list[str] = []
        self._next_id = 100000000

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://zoom.us/oauth/token"):
            self.token_calls += 1
            self.token_requests.append(
                {
                    "authorization": request.headers.get("authorization", ""),
                    "grant_type": request.url.params.get("grant_type", ""),
                    "account_id": request.url.params.get("account_id", ""),
                }
            )
            if self.token_status >= 400:
                return httpx.Response(self.token_status, json={"error": "invalid_client"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"fake-zoom-token-{self.token_calls}",
                    "expires_in": 3600,
                },
            )

        self.auth_headers_seen.append(request.headers.get("authorization", ""))
        if self.force_401_count > 0:
            self.force_401_count -= 1
            return httpx.Response(401, json={"code": 124, "message": "Invalid access token"})

        if request.method == "POST" and url.endswith("/meetings"):
            body = json.loads(request.content)
            self.created_bodies.append(body)
            self._next_id += 1
            meeting_id = str(self._next_id)
            self.meetings[meeting_id] = {**body, "id": self._next_id}
            self.registrants[meeting_id] = []
            return httpx.Response(
                201,
                json={"id": self._next_id, "join_url": f"https://zoom.us/j/{meeting_id}"},
            )
        if request.method == "DELETE" and "/meetings/" in url:
            meeting_id = url.rsplit("/", 1)[-1]
            self.deleted_ids.append(meeting_id)
            return httpx.Response(204)
        if request.method == "GET" and "/registrants" in url:
            meeting_id = url.split("/meetings/", 1)[-1].split("/registrants")[0]
            regs = self.registrants.get(meeting_id)
            if regs is None:
                return httpx.Response(404, json={"message": "meeting not found"})
            return httpx.Response(200, json={"registrants": regs})
        if request.method == "POST" and "/registrants" in url:
            meeting_id = url.split("/meetings/", 1)[-1].split("/registrants")[0]
            body = json.loads(request.content)
            self.registrants.setdefault(meeting_id, []).append(
                {"email": body["email"], "first_name": body["first_name"]}
            )
            return httpx.Response(201, json={"registrant_id": uuid.uuid4().hex})
        if request.method == "PUT" and "/registrants/status" in url:
            meeting_id = url.split("/meetings/", 1)[-1].split("/registrants")[0]
            body = json.loads(request.content)
            targets = {r["email"].lower() for r in body["registrants"]}
            self.registrants[meeting_id] = [
                r for r in self.registrants.get(meeting_id, []) if r["email"].lower() not in targets
            ]
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def fake_zoom(monkeypatch: pytest.MonkeyPatch) -> FakeZoom:
    fake = FakeZoom()
    real_client = httpx.AsyncClient

    def patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = fake
        return real_client(*args, **kwargs)

    monkeypatch.setattr(zoom.httpx, "AsyncClient", patched)
    monkeypatch.setattr(zoom, "_cached_token", None)
    monkeypatch.setattr(zoom, "_cached_token_expiry", 0.0)
    return fake


class _FakeWorkshopSession:
    starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    ends_at = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)


async def test_unconfigured_refuses_before_any_http_call(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings(zoom_organiser_email=""))
    with pytest.raises(MeetingProviderUnavailable):
        await provider.create_meeting(
            session=_FakeWorkshopSession(),  # type: ignore[arg-type]
            organiser_user_id=uuid.uuid4(),
            attendee_emails=["facilitator@example.com"],
        )
    assert fake_zoom.token_calls == 0


async def test_token_request_shape(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    await provider._get_token()
    assert fake_zoom.token_calls == 1
    req = fake_zoom.token_requests[0]
    assert req["grant_type"] == "account_credentials"
    assert req["account_id"] == "test-account-id"
    expected_basic = base64.b64encode(b"test-client-id:test-client-secret").decode()
    assert req["authorization"] == f"Basic {expected_basic}"


async def test_token_is_cached_across_calls(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    first = await provider._get_token()
    second = await provider._get_token()
    assert first == second == "fake-zoom-token-1"
    assert fake_zoom.token_calls == 1


async def test_bad_credentials_raise_cleanly(fake_zoom: FakeZoom) -> None:
    fake_zoom.token_status = 401
    provider = ZoomMeetingProvider(_settings())
    with pytest.raises(MeetingProviderUnavailable):
        await provider._get_token()


async def test_create_meeting_sends_expected_body_and_parses_response(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator-a@example.com", "facilitator-b@example.com"],
    )
    assert details.provider == "zoom"
    assert details.provider_meeting_id is not None
    assert details.join_url == f"https://zoom.us/j/{details.provider_meeting_id}"

    assert len(fake_zoom.created_bodies) == 1
    body = fake_zoom.created_bodies[0]
    assert body["type"] == 2
    assert body["start_time"] == "2026-09-01T09:00:00"
    assert body["timezone"] == "UTC"
    assert body["duration"] == 90
    assert body["settings"]["alternative_hosts"] == (
        "facilitator-a@example.com,facilitator-b@example.com"
    )


async def test_create_meeting_with_no_facilitators_sends_no_alternative_hosts(
    fake_zoom: FakeZoom,
) -> None:
    provider = ZoomMeetingProvider(_settings())
    await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=[],
    )
    assert "alternative_hosts" not in fake_zoom.created_bodies[0]["settings"]


async def test_cancel_meeting_deletes_it(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=[],
    )
    await provider.cancel_meeting(provider_meeting_id=details.provider_meeting_id)
    assert fake_zoom.deleted_ids == [details.provider_meeting_id]


async def test_cancel_meeting_is_a_noop_with_no_meeting_id(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    await provider.cancel_meeting(provider_meeting_id=None)
    assert fake_zoom.deleted_ids == []
    assert fake_zoom.token_calls == 0


async def test_add_then_remove_attendee_round_trips_through_registrants(
    fake_zoom: FakeZoom,
) -> None:
    provider = ZoomMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator@example.com"],
    )
    meeting_id = details.provider_meeting_id
    assert meeting_id is not None

    await provider.add_attendee(provider_meeting_id=meeting_id, email="learner@example.com")
    emails = {r["email"] for r in fake_zoom.registrants[meeting_id]}
    assert emails == {"learner@example.com"}
    assert fake_zoom.registrants[meeting_id][0]["first_name"] == "Learner"

    # Adding the same learner again is a no-op, not a duplicate registrant.
    await provider.add_attendee(provider_meeting_id=meeting_id, email="learner@example.com")
    assert len(fake_zoom.registrants[meeting_id]) == 1

    await provider.remove_attendee(provider_meeting_id=meeting_id, email="learner@example.com")
    assert fake_zoom.registrants[meeting_id] == []

    # Removing someone who was never a registrant is also a clean no-op.
    await provider.remove_attendee(provider_meeting_id=meeting_id, email="stranger@example.com")
    assert fake_zoom.registrants[meeting_id] == []


async def test_registrant_first_name_derived_from_email_local_part(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=[],
    )
    meeting_id = details.provider_meeting_id
    assert meeting_id is not None
    await provider.add_attendee(provider_meeting_id=meeting_id, email="grace.hopper@example.com")
    assert fake_zoom.registrants[meeting_id][0]["first_name"] == "Grace Hopper"


async def test_a_stale_cached_token_is_retried_once_with_a_fresh_one(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    await provider._get_token()
    assert fake_zoom.token_calls == 1

    fake_zoom.force_401_count = 1
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator@example.com"],
    )
    assert details.provider_meeting_id is not None
    assert fake_zoom.token_calls == 2
    assert fake_zoom.auth_headers_seen == [
        "Bearer fake-zoom-token-1",
        "Bearer fake-zoom-token-2",
    ]
    await provider.cancel_meeting(provider_meeting_id=details.provider_meeting_id)
    assert fake_zoom.token_calls == 2


async def test_two_consecutive_401s_still_raise_cleanly(fake_zoom: FakeZoom) -> None:
    provider = ZoomMeetingProvider(_settings())
    fake_zoom.force_401_count = 2
    with pytest.raises(MeetingProviderUnavailable):
        await provider.create_meeting(
            session=_FakeWorkshopSession(),  # type: ignore[arg-type]
            organiser_user_id=uuid.uuid4(),
            attendee_emails=[],
        )
    assert fake_zoom.token_calls == 2
