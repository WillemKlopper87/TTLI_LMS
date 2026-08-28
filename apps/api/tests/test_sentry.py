"""core/logging.py::init_sentry.

`check_production_safety` has required SENTRY_DSN to be set since it was
written, but nothing ever imported sentry_sdk to act on it -- these tests
exist specifically because a config-only guard is easy to leave unverified.
The important one isn't "does init_sentry run without raising"; it's
"does a genuinely unhandled exception, raised the same way a real bug
would be, actually reach the SDK" -- proven against the same three
exception handlers main.py registers, not a toy app.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from unittest.mock import patch

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.transport import Transport
from src.core.config import Settings
from src.core.errors import (
    AppError,
    NotFound,
    app_error_handler,
    http_error_handler,
    validation_error_handler,
)
from src.core.logging import init_sentry
from starlette.exceptions import HTTPException as StarletteHTTPException

GOOD_KEY = base64.b64encode(b"A" * 32).decode()
OTHER_KEY = base64.b64encode(b"B" * 32).decode()


@pytest.fixture(autouse=True)
def _restore_sentry_client() -> Iterator[None]:
    """These tests call the real `sentry_sdk.init` (that's the point --
    testing the wiring, not a mock of it), which mutates process-global SDK
    state. Restore whatever client existed before this file ran, so no
    later test can send through an active client left behind here.

    One thing this does NOT undo: `StarletteIntegration.setup_once()`
    monkey-patches Starlette's exception-handling methods once per process,
    with no supported "uninstall" -- inherent to how sentry_sdk's real
    integrations work, not something a fixture can fix. Harmless (the
    patched wrapper is a no-op once the client is inactive again) but
    visible: an unrelated test elsewhere in the suite may show this
    module's frame in a warning's stack attribution after this file runs.
    """
    original = sentry_sdk.get_global_scope().client
    yield
    sentry_sdk.get_global_scope().set_client(original)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "secret_key": "x" * 48,
        "database_url": "postgresql+asyncpg://u:p@db.internal:5432/ttli",
        "field_encryption_key": GOOD_KEY,
        "blind_index_key": OTHER_KEY,
        "storage_backend": "s3",
        "s3_access_key": "AKIAREAL",
        "app_db_password": "K9mP2xQ7vN4wZ8bR",
        "redis_url": "redis://u:p@redis.internal:6379/0",
        "sentry_dsn": "",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _RecordingTransport(Transport):
    """Stands in for the real network transport -- records every envelope
    instead of sending it anywhere, so a test can assert on what would
    have been sent without a real Sentry project."""

    def __init__(self, options: dict[str, object] | None = None) -> None:
        super().__init__(options)
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)


def test_init_sentry_is_a_noop_without_a_dsn() -> None:
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(_settings(sentry_dsn=""))
    mock_init.assert_not_called()


def test_init_sentry_configures_the_sdk_with_a_dsn() -> None:
    init_sentry(_settings(sentry_dsn="https://examplekey@o0.ingest.sentry.io/1"))
    client = sentry_sdk.get_client()
    assert client.is_active()
    options = client.options
    assert options["environment"] == "production"
    assert options["release"] == "ttli-api@0.1.0"
    assert options["send_default_pii"] is False
    assert options["traces_sample_rate"] == 0


async def test_a_genuinely_unhandled_exception_reaches_sentry() -> None:
    """The real point of wiring this up: a bug that isn't one of the
    deliberate AppError/HTTPException/RequestValidationError refusals
    every route already handles must still surface somewhere other than
    stdout. Mirrors main.py's own exception-handler registration exactly
    -- if this app were wired differently, this test would be testing the
    wrong thing."""
    transport = _RecordingTransport({"dsn": "https://examplekey@o0.ingest.sentry.io/1"})
    sentry_sdk.init(
        dsn="https://examplekey@o0.ingest.sentry.io/1",
        environment="production",
        integrations=[StarletteIntegration(), FastApiIntegration()],
        transport=transport,
    )

    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("a real, unanticipated bug")

    @app.get("/expected-404")
    async def expected_404() -> None:
        raise NotFound("No such resource.")

    transport.envelopes.clear()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=10.0
    ) as client:
        # A deliberate AppError refusal -- handled cleanly by the app's own
        # handler, never reaches Sentry as an incident.
        expected = await client.get("/expected-404")
        assert expected.status_code == 404
        assert transport.envelopes == []

        # A genuine unhandled exception -- this is the one that must reach
        # the SDK, since nothing in main.py's handler list catches it.
        try:
            await client.get("/boom")
        except RuntimeError:
            pass  # httpx's ASGI transport re-raises; the capture already happened.

    assert len(transport.envelopes) == 1
    events = transport.envelopes[0].items
    error_events = [item.payload.json for item in events if item.data_category == "error"]
    assert len(error_events) == 1
    error_event = error_events[0]
    assert error_event is not None
    exc_values = error_event["exception"]["values"]
    assert exc_values[-1]["type"] == "RuntimeError"
    assert exc_values[-1]["value"] == "a real, unanticipated bug"
