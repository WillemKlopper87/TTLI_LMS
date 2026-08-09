"""The arq worker.

Run with:  arq src.workers.main.WorkerSettings   (from apps/api)

Both maintenance jobs are thin wrappers over SECURITY DEFINER SQL functions
installed by migration 0005 — the privilege to create partitions or delete
across tenants lives in the database function's owner, never in this
process, which connects as the same least-privileged app_user as the API.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from arq import func
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import text

from src.core.config import get_settings
from src.core.db import dispose_engine, get_sessionmaker, init_engine
from src.core.logging import configure_logging, get_logger
from src.services.email import send_sync

log = get_logger(__name__)


async def extend_event_partitions(ctx: dict[str, Any]) -> int:
    """Keep ~12 months of events partitions ahead of now. Idempotent."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        created = (await session.execute(text("SELECT extend_events_partitions(12)"))).scalar_one()
    log.info("events_partitions_extended", created=created)
    return int(created)


async def purge_expired_auth(ctx: dict[str, Any]) -> int:
    """Delete refresh tokens, magic links and password resets whose expiry is
    more than 30 days past. The grace period keeps recent rows available to
    the reuse-detection path and for incident forensics."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        purged = (await session.execute(text("SELECT purge_expired_auth_rows(30)"))).scalar_one()
    log.info("expired_auth_rows_purged", purged=purged)
    return int(purged)


async def send_email_job(ctx: dict[str, Any], *, to: str, subject: str, body: str) -> None:
    """Raises on any SMTP failure so arq retries with backoff (max_tries
    below) instead of the message being silently dropped — the one thing
    services/email.py's old fire-and-forget swallow could never do."""
    settings = get_settings()
    await asyncio.to_thread(send_sync, settings, to=to, subject=subject, body=body)
    log.info("email_sent", to_domain=to.rsplit("@", 1)[-1])


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, pretty=settings.environment == "local")
    init_engine(settings)
    log.info("worker_started", environment=settings.environment)


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_engine()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        extend_event_partitions,
        purge_expired_auth,
        func(send_email_job, max_tries=5),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        # Partitions monthly on the 1st; 0004 bootstrapped ~13 months of
        # runway, so a missed run is survivable for a long time.
        cron(extend_event_partitions, day=1, hour=2, minute=0),
        cron(purge_expired_auth, hour=3, minute=30),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)


__all__ = ["WorkerSettings", "extend_event_partitions", "purge_expired_auth", "send_email_job"]
