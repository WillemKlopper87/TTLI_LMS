"""Structured logging and error tracking.

JSON in every environment except local, where a human has to read it.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.core.config import Settings


def configure_logging(*, level: str = "INFO", pretty: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())

    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer() if pretty else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def init_sentry(settings: Settings) -> None:
    """Wire up real error tracking — `check_production_safety` has refused
    to boot in production without a `SENTRY_DSN` since that check was
    written, but nothing ever imported `sentry_sdk` to act on the value.
    That made the gap look closed when it wasn't: a genuine unhandled
    exception (a real bug, not one of the deliberate `AppError`/
    `StarletteHTTPException` refusals every route already handles and
    responds to cleanly) would be diagnosable only from raw stdout.

    A no-op with an empty DSN, same as every other unconfigured-third-party
    path in this codebase (Payfast, Spotify, VAPID, Graph) — local/CI never
    sets one and must not try to reach anywhere.

    Scope is deliberately narrow: error capture only. `traces_sample_rate`
    stays at 0 — full performance tracing/APM is real future work (`docs/
    BACKLOG.md` O1), not something this change claims to have finished.
    `send_default_pii=False` is already the SDK default; set explicitly
    here because this codebase's whole design (field encryption, blind
    indexes, `04_SECURITY`) exists specifically to keep PII out of paths
    like this one.
    """
    if not settings.sentry_dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release="ttli-api@0.1.0",
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0,
        send_default_pii=False,
    )


__all__ = ["configure_logging", "get_logger", "init_sentry"]
