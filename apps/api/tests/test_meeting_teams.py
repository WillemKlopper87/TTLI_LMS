"""`services/meeting/teams.py` (P7 phase 5, REQ-WS-05/06).

No DB/Redis needed — same class of pure unit test as `test_ics.py` and
`test_sso.py`'s `fake_idp` fixture, which this borrows its shape from:
a custom `httpx.AsyncBaseTransport` answering Graph's token endpoint
and event resource, `monkeypatch`ed in place of a real connection.
Genuinely live-testing this needs an Azure AD app registration nobody
has provisioned in this environment (see the module's own docstring);
this is the achievable bar — assert the exact requests sent and the
exact responses parsed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from src.core.config import Settings
from src.services.meeting import teams
from src.services.meeting.base import MeetingProviderUnavailable
from src.services.meeting.teams import TeamsMeetingProvider


def _settings(**overrides: str) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "graph_client_id": "test-client-id",
        "graph_client_secret": "test-client-secret",
        "graph_tenant_id": "test-tenant-id",
        "graph_organiser_upn": "workshops@ttli.example.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class FakeGraph(httpx.AsyncBaseTransport):
    """Answers the token endpoint and a single event resource. Anything
    else 404s, so an unexpected outbound call fails loudly."""

    def __init__(self) -> None:
        self.token_requests: list[dict[str, str]] = []
        self.token_calls = 0
        self.events: dict[str, dict[str, Any]] = {}
        self.created_bodies: list[dict[str, Any]] = []
        self.deleted_ids: list[str] = []
        self.token_status = 200
        # F9: force the next N non-token calls to 401, regardless of
        # which token was presented — simulates a secret rotated in
        # Azure mid-lifetime, which invalidates a cached-but-still-
        # unexpired token.
        self.force_401_count = 0
        self.auth_headers_seen: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/oauth2/v2.0/token"):
            self.token_calls += 1
            form = dict(
                pair.split("=", 1) for pair in request.content.decode().split("&") if "=" in pair
            )
            self.token_requests.append(form)
            if self.token_status >= 400:
                return httpx.Response(self.token_status, json={"error": "invalid_client"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"fake-graph-token-{self.token_calls}",
                    "expires_in": 3600,
                },
            )

        self.auth_headers_seen.append(request.headers.get("authorization", ""))
        if self.force_401_count > 0:
            self.force_401_count -= 1
            return httpx.Response(401, json={"error": "InvalidAuthenticationToken"})

        if request.method == "POST" and url.endswith("/events"):
            body = json.loads(request.content)
            self.created_bodies.append(body)
            event_id = f"event-{uuid.uuid4().hex[:8]}"
            self.events[event_id] = {**body, "id": event_id}
            return httpx.Response(
                201,
                json={
                    "id": event_id,
                    "onlineMeeting": {
                        "joinUrl": f"https://teams.microsoft.com/l/meetup-join/{event_id}"
                    },
                },
            )
        if request.method == "GET" and "/events/" in url:
            event_id = url.rsplit("/", 1)[-1]
            event = self.events.get(event_id)
            if event is None:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=event)
        if request.method == "PATCH" and "/events/" in url:
            event_id = url.rsplit("/", 1)[-1]
            body = json.loads(request.content)
            self.events.setdefault(event_id, {}).update(body)
            return httpx.Response(200, json=self.events[event_id])
        if request.method == "DELETE" and "/events/" in url:
            event_id = url.rsplit("/", 1)[-1]
            self.deleted_ids.append(event_id)
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    graph = FakeGraph()
    real_client = httpx.AsyncClient

    def patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = graph
        return real_client(*args, **kwargs)

    monkeypatch.setattr(teams.httpx, "AsyncClient", patched)
    # The token cache is module-level (platform-wide credentials, not
    # per-tenant) — reset it so one test's token doesn't leak into the
    # next and silently suppress the very call-count assertions below.
    monkeypatch.setattr(teams, "_cached_token", None)
    monkeypatch.setattr(teams, "_cached_token_expiry", 0.0)
    return graph


class _FakeWorkshopSession:
    starts_at = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    ends_at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


async def test_unconfigured_refuses_before_any_http_call(fake_graph: FakeGraph) -> None:
    provider = TeamsMeetingProvider(_settings(graph_organiser_upn=""))
    with pytest.raises(MeetingProviderUnavailable):
        await provider.create_meeting(
            session=_FakeWorkshopSession(),  # type: ignore[arg-type]
            organiser_user_id=uuid.uuid4(),
            attendee_emails=["facilitator@example.com"],
        )
    assert fake_graph.token_calls == 0


async def test_token_request_shape(fake_graph: FakeGraph) -> None:
    provider = TeamsMeetingProvider(_settings())
    await provider._get_token()
    assert fake_graph.token_calls == 1
    body = fake_graph.token_requests[0]
    assert body["grant_type"] == "client_credentials"
    assert body["client_id"] == "test-client-id"
    assert body["client_secret"] == "test-client-secret"
    assert body["scope"] == "https%3A%2F%2Fgraph.microsoft.com%2F.default"


async def test_token_is_cached_across_calls(fake_graph: FakeGraph) -> None:
    provider = TeamsMeetingProvider(_settings())
    first = await provider._get_token()
    second = await provider._get_token()
    assert first == second == "fake-graph-token-1"
    assert fake_graph.token_calls == 1


async def test_bad_credentials_raise_cleanly(fake_graph: FakeGraph) -> None:
    fake_graph.token_status = 401
    provider = TeamsMeetingProvider(_settings())
    with pytest.raises(MeetingProviderUnavailable):
        await provider._get_token()


async def test_create_meeting_sends_expected_event_body_and_parses_response(
    fake_graph: FakeGraph,
) -> None:
    provider = TeamsMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator-a@example.com", "facilitator-b@example.com"],
    )
    assert details.provider == "teams"
    assert details.provider_meeting_id is not None
    assert details.join_url == (
        f"https://teams.microsoft.com/l/meetup-join/{details.provider_meeting_id}"
    )

    assert len(fake_graph.created_bodies) == 1
    body = fake_graph.created_bodies[0]
    assert body["isOnlineMeeting"] is True
    assert body["onlineMeetingProvider"] == "teamsForBusiness"
    assert body["start"]["dateTime"] == "2026-09-01T09:00:00+00:00"
    assert body["end"]["dateTime"] == "2026-09-01T10:00:00+00:00"
    addresses = {a["emailAddress"]["address"] for a in body["attendees"]}
    assert addresses == {"facilitator-a@example.com", "facilitator-b@example.com"}


async def test_cancel_meeting_deletes_the_event(fake_graph: FakeGraph) -> None:
    provider = TeamsMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=[],
    )
    await provider.cancel_meeting(provider_meeting_id=details.provider_meeting_id)
    assert fake_graph.deleted_ids == [details.provider_meeting_id]


async def test_cancel_meeting_is_a_noop_with_no_meeting_id(fake_graph: FakeGraph) -> None:
    provider = TeamsMeetingProvider(_settings())
    await provider.cancel_meeting(provider_meeting_id=None)
    assert fake_graph.deleted_ids == []
    assert fake_graph.token_calls == 0


async def test_add_then_remove_attendee_round_trips_through_the_event(
    fake_graph: FakeGraph,
) -> None:
    provider = TeamsMeetingProvider(_settings())
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator@example.com"],
    )
    event_id = details.provider_meeting_id
    assert event_id is not None

    await provider.add_attendee(provider_meeting_id=event_id, email="learner@example.com")
    addresses = {a["emailAddress"]["address"] for a in fake_graph.events[event_id]["attendees"]}
    assert addresses == {"facilitator@example.com", "learner@example.com"}

    # Adding the same learner again is a no-op, not a duplicate attendee.
    await provider.add_attendee(provider_meeting_id=event_id, email="learner@example.com")
    assert len(fake_graph.events[event_id]["attendees"]) == 2

    await provider.remove_attendee(provider_meeting_id=event_id, email="learner@example.com")
    addresses = {a["emailAddress"]["address"] for a in fake_graph.events[event_id]["attendees"]}
    assert addresses == {"facilitator@example.com"}


async def test_a_stale_cached_token_is_retried_once_with_a_fresh_one(
    fake_graph: FakeGraph,
) -> None:
    """Overall-review F9: the token cache expires only by clock, so a
    client secret rotated in Azure mid-lifetime would otherwise fail
    every call for up to ~55 minutes. On a 401, _request must drop the
    cache, fetch a genuinely fresh token, and retry exactly once."""
    provider = TeamsMeetingProvider(_settings())
    # Warm the cache with a token Graph is about to start rejecting.
    await provider._get_token()
    assert fake_graph.token_calls == 1

    fake_graph.force_401_count = 1
    details = await provider.create_meeting(
        session=_FakeWorkshopSession(),  # type: ignore[arg-type]
        organiser_user_id=uuid.uuid4(),
        attendee_emails=["facilitator@example.com"],
    )
    assert details.provider_meeting_id is not None
    # A second token was fetched (the retry), and the two auth headers
    # sent to Graph for the real request differ — the stale one that
    # got 401'd, then the fresh one that succeeded.
    assert fake_graph.token_calls == 2
    assert fake_graph.auth_headers_seen == [
        "Bearer fake-graph-token-1",
        "Bearer fake-graph-token-2",
    ]
    # The provider's own cache now holds the fresh token, not the one
    # that was just invalidated — the next call makes zero token calls.
    await provider.cancel_meeting(provider_meeting_id=details.provider_meeting_id)
    assert fake_graph.token_calls == 2


async def test_two_consecutive_401s_still_raise_cleanly(fake_graph: FakeGraph) -> None:
    """The retry is a single attempt, not a loop — a Graph outage that
    401s persistently must still surface as a clean refusal, not hang
    or retry indefinitely."""
    provider = TeamsMeetingProvider(_settings())
    fake_graph.force_401_count = 2
    with pytest.raises(MeetingProviderUnavailable):
        await provider.create_meeting(
            session=_FakeWorkshopSession(),  # type: ignore[arg-type]
            organiser_user_id=uuid.uuid4(),
            attendee_emails=[],
        )
    assert fake_graph.token_calls == 2
