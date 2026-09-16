"""T11 observability: metrics wiring, worker instrumentation, storage
counters and the async sampler's independent-failure handling.

Unit-only — nothing here needs a live Postgres/Redis except
`test_refresh_operational_metrics_*`, which fake both dependencies rather
than reach out, so this whole module runs in the fast tier.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from arq import Retry
from src.core.metrics import (
    OBSERVABILITY_SAMPLER_FAILURES,
    STORAGE_OPERATIONS,
    WORKER_JOB_ATTEMPTS,
    set_database_pool_metrics,
    set_database_runtime_metrics,
    set_queue_depth,
    start_metrics_server,
    stop_metrics_server,
)
from src.services.storage.base import Container
from src.services.storage.local import LocalStorageAdapter
from src.services.storage.observed import ObservedStorageService
from src.workers.observability import instrument_job


def _counter_value(counter: Any, *labels: str) -> float:
    value: float = counter.labels(*labels)._value.get()
    return value


async def test_instrument_job_counts_success() -> None:
    @instrument_job
    async def ok(ctx: dict[str, Any]) -> str:
        return "done"

    before = _counter_value(WORKER_JOB_ATTEMPTS, "ok", "success")
    assert await ok({}) == "done"
    assert _counter_value(WORKER_JOB_ATTEMPTS, "ok", "success") == before + 1


async def test_instrument_job_counts_error_and_reraises() -> None:
    @instrument_job
    async def boom(ctx: dict[str, Any]) -> None:
        raise ValueError("nope")

    before = _counter_value(WORKER_JOB_ATTEMPTS, "boom", "error")
    with pytest.raises(ValueError, match="nope"):
        await boom({})
    assert _counter_value(WORKER_JOB_ATTEMPTS, "boom", "error") == before + 1


async def test_instrument_job_counts_retry_distinctly_from_error() -> None:
    @instrument_job
    async def flaky(ctx: dict[str, Any]) -> None:
        raise Retry()

    before = _counter_value(WORKER_JOB_ATTEMPTS, "flaky", "retry")
    with pytest.raises(Retry):
        await flaky({})
    assert _counter_value(WORKER_JOB_ATTEMPTS, "flaky", "retry") == before + 1


async def test_instrument_job_counts_cancellation() -> None:
    @instrument_job
    async def slow(ctx: dict[str, Any]) -> None:
        raise asyncio.CancelledError()

    before = _counter_value(WORKER_JOB_ATTEMPTS, "slow", "cancelled")
    with pytest.raises(asyncio.CancelledError):
        await slow({})
    assert _counter_value(WORKER_JOB_ATTEMPTS, "slow", "cancelled") == before + 1


async def test_instrument_job_preserves_the_wrapped_functions_name() -> None:
    @instrument_job
    async def named_job(ctx: dict[str, Any]) -> None:
        return None

    assert named_job.__name__ == "named_job"


def test_metrics_server_start_is_idempotent_and_off_switch_works() -> None:
    # port <= 0 is the explicit no-op used by tests/local tooling; must not
    # bind a socket or raise.
    start_metrics_server(0)
    stop_metrics_server()
    stop_metrics_server()  # stopping an already-stopped server is a no-op


def test_pool_and_runtime_gauge_setters_round_trip() -> None:
    set_database_pool_metrics(size=5, checked_out=2, overflow=0)
    set_database_runtime_metrics(connections=3, max_connections=100, size_bytes=1024)
    set_queue_depth(-5)  # never publish a negative depth
    from src.core.metrics import QUEUE_DEPTH

    assert QUEUE_DEPTH._value.get() == 0


async def test_observed_storage_service_counts_ok_and_error(tmp_path: Any) -> None:
    adapter = ObservedStorageService(LocalStorageAdapter(str(tmp_path)), backend="local")
    container = Container.PRIVATE_CONTENT

    ok_before = _counter_value(STORAGE_OPERATIONS, "local", "upload_object", container, "ok")
    await adapter.upload_object(container, "obs-test.txt", b"data", content_type="text/plain")
    assert (
        _counter_value(STORAGE_OPERATIONS, "local", "upload_object", container, "ok")
        == ok_before + 1
    )

    not_found_before = _counter_value(
        STORAGE_OPERATIONS, "local", "get_object", container, "not_found"
    )
    from src.services.storage.base import ObjectNotFound

    with pytest.raises(ObjectNotFound):
        await adapter.get_object(container, "does-not-exist.txt")
    assert (
        _counter_value(STORAGE_OPERATIONS, "local", "get_object", container, "not_found")
        == not_found_before + 1
    )


async def test_refresh_operational_metrics_survives_a_database_failure(monkeypatch: Any) -> None:
    """A database sampling failure must not suppress the queue-depth gauge —
    the two probes are deliberately independent (core/observability.py)."""
    from src.core import observability

    async def failing_database_stats() -> Any:
        raise RuntimeError("db unreachable")

    class FakeRedis:
        async def zcard(self, name: str) -> int:
            return 7

    monkeypatch.setattr(observability, "database_runtime_stats", failing_database_stats)
    monkeypatch.setattr(observability, "get_redis", lambda: FakeRedis())

    failures_before = _counter_value(OBSERVABILITY_SAMPLER_FAILURES, "database")
    await observability.refresh_operational_metrics()

    assert _counter_value(OBSERVABILITY_SAMPLER_FAILURES, "database") == failures_before + 1
    from src.core.metrics import QUEUE_DEPTH

    assert QUEUE_DEPTH._value.get() == 7


async def test_refresh_operational_metrics_survives_a_redis_failure(monkeypatch: Any) -> None:
    from src.core import observability
    from src.core.db import DatabaseRuntimeStats

    async def working_database_stats() -> DatabaseRuntimeStats:
        return DatabaseRuntimeStats(connections=1, max_connections=100, size_bytes=2048)

    class FailingRedis:
        async def zcard(self, name: str) -> int:
            raise RuntimeError("redis unreachable")

    monkeypatch.setattr(observability, "database_runtime_stats", working_database_stats)
    monkeypatch.setattr(observability, "get_redis", lambda: FailingRedis())

    failures_before = _counter_value(OBSERVABILITY_SAMPLER_FAILURES, "queue")
    await observability.refresh_operational_metrics()

    assert _counter_value(OBSERVABILITY_SAMPLER_FAILURES, "queue") == failures_before + 1
