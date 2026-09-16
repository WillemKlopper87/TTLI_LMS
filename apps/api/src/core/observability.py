"""Asynchronous gauges that cannot be collected from a scrape thread alone."""

from __future__ import annotations

import asyncio

from arq.constants import default_queue_name

from src.core.db import database_pool_stats, database_runtime_stats
from src.core.logging import get_logger
from src.core.metrics import (
    OBSERVABILITY_SAMPLER_FAILURES,
    set_database_pool_metrics,
    set_database_runtime_metrics,
    set_queue_depth,
)
from src.core.redis import get_redis

log = get_logger(__name__)

API_METRICS_PORT = 9101
WORKER_METRICS_PORT = 9102
SAMPLE_INTERVAL_SECONDS = 15


async def refresh_operational_metrics() -> None:
    """Refresh queue and PostgreSQL gauges once.

    Pool metrics are process-local and cannot fail. Database/Redis probes are
    deliberately independent: a Redis outage must not suppress database
    telemetry, and vice versa. Failures increment their own counter and are
    logged without making observability a new application availability
    dependency.
    """

    pool = database_pool_stats()
    set_database_pool_metrics(
        size=pool.size,
        checked_out=pool.checked_out,
        overflow=pool.overflow,
    )

    try:
        database = await database_runtime_stats()
    except Exception:
        OBSERVABILITY_SAMPLER_FAILURES.labels("database").inc()
        log.warning("observability_database_sample_failed", exc_info=True)
    else:
        set_database_runtime_metrics(
            connections=database.connections,
            max_connections=database.max_connections,
            size_bytes=database.size_bytes,
        )

    try:
        depth = await get_redis().zcard(default_queue_name)
    except Exception:
        OBSERVABILITY_SAMPLER_FAILURES.labels("queue").inc()
        log.warning("observability_queue_sample_failed", exc_info=True)
    else:
        set_queue_depth(int(depth))


async def sample_operational_metrics(*, interval_seconds: int = SAMPLE_INTERVAL_SECONDS) -> None:
    while True:
        await refresh_operational_metrics()
        await asyncio.sleep(interval_seconds)


__all__ = [
    "API_METRICS_PORT",
    "SAMPLE_INTERVAL_SECONDS",
    "WORKER_METRICS_PORT",
    "refresh_operational_metrics",
    "sample_operational_metrics",
]
