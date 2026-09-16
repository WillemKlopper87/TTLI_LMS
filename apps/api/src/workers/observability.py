"""Worker-side job correlation and attempt metrics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from time import perf_counter
from typing import Any, TypeVar, cast

import structlog
from arq import Retry

from src.core.logging import get_logger
from src.core.metrics import WORKER_JOB_ATTEMPTS, WORKER_JOB_DURATION

log = get_logger(__name__)

# Bound, not aliased, so the decorator returns arq's own registered-function
# type unchanged (e.g. WorkerCoroutine) instead of widening every job to the
# same loose Callable[..., Awaitable[Any]] shape that arq's func()/cron()
# stubs then reject.
JobCallable = TypeVar("JobCallable", bound=Callable[..., Awaitable[Any]])


def instrument_job(function: JobCallable) -> JobCallable:
    """Wrap one arq function without changing the name arq registers.

    A failed *attempt* is counted even when arq will retry it. That distinction
    is useful operationally: a queue can eventually drain while repeatedly
    failing SMTP/storage/provider calls. Job IDs and try numbers go to the
    structured log context, never to metric labels.
    """

    @wraps(function)
    async def observed(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        job_name = function.__name__
        started = perf_counter()
        outcome = "error"
        with structlog.contextvars.bound_contextvars(
            job_id=str(ctx.get("job_id", "unknown")),
            job_try=int(ctx.get("job_try", 1)),
            job_name=job_name,
        ):
            try:
                result = await function(ctx, *args, **kwargs)
            except Retry:
                outcome = "retry"
                raise
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except Exception:
                outcome = "error"
                raise
            else:
                outcome = "success"
                return result
            finally:
                duration = perf_counter() - started
                WORKER_JOB_ATTEMPTS.labels(job_name, outcome).inc()
                WORKER_JOB_DURATION.labels(job_name, outcome).observe(duration)
                log.info(
                    "worker_job_attempt_finished",
                    outcome=outcome,
                    duration_ms=round(duration * 1000, 2),
                )

    return cast(JobCallable, observed)


__all__ = ["instrument_job"]
