"""Low-cardinality operational metrics for the API and worker.

The single-VM deployment scrapes these on internal-only ports. Nothing in this
module assumes Prometheus is the final backend: the metric names and labels are
the application contract, while the collector can be replaced by Azure Monitor
when the documented target architecture lands.

Never put tenant IDs, user IDs, hostnames, object keys, URLs or exception text
in labels. Those are both PII/cardinality hazards and belong in structured logs,
not time-series dimensions.
"""

from __future__ import annotations

from threading import Thread
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

HTTP_REQUESTS = Counter(
    "ttli_http_requests_total",
    "Completed API requests.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "ttli_http_request_duration_seconds",
    "API request duration in seconds.",
    ("method", "route"),
    buckets=(0.05, 0.1, 0.25, 0.5, 0.8, 1.0, 2.0, 5.0, 10.0),
)

QUEUE_DEPTH = Gauge(
    "ttli_queue_depth",
    "Jobs waiting in the default arq queue.",
)
WORKER_JOB_ATTEMPTS = Counter(
    "ttli_worker_job_attempts_total",
    "Worker job attempts by terminal outcome for this attempt.",
    ("job", "outcome"),
)
WORKER_JOB_DURATION = Histogram(
    "ttli_worker_job_duration_seconds",
    "Worker job attempt duration in seconds.",
    ("job", "outcome"),
    buckets=(0.05, 0.25, 1.0, 5.0, 15.0, 60.0, 300.0, 1800.0, 21600.0),
)

DATABASE_POOL_SIZE = Gauge(
    "ttli_database_pool_size",
    "Configured SQLAlchemy connection-pool size.",
)
DATABASE_POOL_CHECKED_OUT = Gauge(
    "ttli_database_pool_checked_out",
    "SQLAlchemy connections currently checked out.",
)
DATABASE_POOL_OVERFLOW = Gauge(
    "ttli_database_pool_overflow",
    "SQLAlchemy overflow connections currently allocated.",
)
DATABASE_CONNECTIONS = Gauge(
    "ttli_database_connections",
    "Connections to the current PostgreSQL database.",
)
DATABASE_MAX_CONNECTIONS = Gauge(
    "ttli_database_max_connections",
    "PostgreSQL max_connections setting.",
)
DATABASE_SIZE_BYTES = Gauge(
    "ttli_database_size_bytes",
    "Size of the current PostgreSQL database in bytes.",
)

STORAGE_OPERATIONS = Counter(
    "ttli_storage_operations_total",
    "Object-storage operations by backend, operation and outcome.",
    ("backend", "operation", "container", "outcome"),
)
OBSERVABILITY_SAMPLER_FAILURES = Counter(
    "ttli_observability_sampler_failures_total",
    "Failures while refreshing asynchronous operational gauges.",
    ("sampler",),
)

_metrics_server: Any | None = None
_metrics_thread: Thread | None = None


def start_metrics_server(port: int) -> None:
    """Start one internal Prometheus HTTP endpoint in this process.

    API and worker run in separate containers and therefore each have their own
    process-local server. ``port <= 0`` is an explicit off switch for tests or
    unusual local tooling.
    """

    global _metrics_server, _metrics_thread
    if port <= 0 or _metrics_server is not None:
        return
    server, thread = start_http_server(port, addr="0.0.0.0")  # noqa: S104
    _metrics_server = server
    _metrics_thread = thread


def stop_metrics_server() -> None:
    global _metrics_server, _metrics_thread
    if _metrics_server is None:
        return
    _metrics_server.shutdown()
    _metrics_server.server_close()
    if _metrics_thread is not None:
        _metrics_thread.join(timeout=2)
    _metrics_server = None
    _metrics_thread = None


def set_queue_depth(depth: int) -> None:
    QUEUE_DEPTH.set(max(depth, 0))


def set_database_pool_metrics(*, size: int, checked_out: int, overflow: int) -> None:
    DATABASE_POOL_SIZE.set(size)
    DATABASE_POOL_CHECKED_OUT.set(checked_out)
    DATABASE_POOL_OVERFLOW.set(overflow)


def set_database_runtime_metrics(
    *, connections: int, max_connections: int, size_bytes: int
) -> None:
    DATABASE_CONNECTIONS.set(connections)
    DATABASE_MAX_CONNECTIONS.set(max_connections)
    DATABASE_SIZE_BYTES.set(size_bytes)


__all__ = [
    "HTTP_REQUESTS",
    "HTTP_REQUEST_DURATION",
    "OBSERVABILITY_SAMPLER_FAILURES",
    "STORAGE_OPERATIONS",
    "WORKER_JOB_ATTEMPTS",
    "WORKER_JOB_DURATION",
    "set_database_pool_metrics",
    "set_database_runtime_metrics",
    "set_queue_depth",
    "start_metrics_server",
    "stop_metrics_server",
]
