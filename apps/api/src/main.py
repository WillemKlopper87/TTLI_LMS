"""Application entry point."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from time import perf_counter

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.config import check_production_safety, get_settings
from src.core.db import dispose_engine, init_engine
from src.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    validation_error_handler,
)
from src.core.idempotency import idempotency_middleware
from src.core.logging import configure_logging, get_logger, init_sentry
from src.core.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    start_metrics_server,
    stop_metrics_server,
)
from src.core.observability import API_METRICS_PORT, sample_operational_metrics
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.routers import (
    analytics,
    articles,
    assessment,
    audit,
    auth,
    campaigns,
    catalogue,
    course_wizard,
    courses,
    credentials,
    deals,
    events,
    guest_access,
    health,
    invoices,
    leads,
    learning,
    learning_paths,
    licence,
    media,
    operations,
    orders,
    organisations,
    platform,
    podcasts,
    privacy,
    push,
    recommendations,
    sso,
    subscriptions,
    tenant,
    tenant_branding,
    tenant_users,
    webhooks,
    workshops,
)

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, pretty=settings.environment == "local")

    problems = check_production_safety(settings)
    if problems:
        # Every problem at once, rather than one per redeploy.
        for problem in problems:
            log.error("production_safety_violation", problem=problem)
        raise RuntimeError(
            f"Refusing to start in production with {len(problems)} unsafe settings: "
            + "; ".join(problems)
        )

    init_sentry(settings)
    init_engine(settings)
    init_redis(settings)
    await init_queue(settings)
    start_metrics_server(API_METRICS_PORT)
    sampler = asyncio.create_task(sample_operational_metrics(), name="operational-metrics")
    log.info("api_started", environment=settings.environment, metrics_port=API_METRICS_PORT)
    try:
        yield
    finally:
        sampler.cancel()
        with suppress(asyncio.CancelledError):
            await sampler
        stop_metrics_server()
        await dispose_engine()
        await dispose_redis()
        await dispose_queue()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="TTLI Executive Training Platform",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Registered before request_context below so that request_context ends
    # up outermost — Starlette builds its middleware stack in the reverse
    # of registration order, so whichever of these two is registered
    # *last* runs *first* on a request. request_context needs to run
    # first: it binds request_id into structlog's context, which
    # error_envelope (core/errors.py) reads via request.state.request_id
    # for every 400/409 idempotency_middleware itself can emit.
    app.middleware("http")(idempotency_middleware)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        status_code = 500
        response: Response | None = None
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route_obj = request.scope.get("route")
            route = str(getattr(route_obj, "path", "<unmatched>"))
            duration = perf_counter() - started
            HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(request.method, route).observe(duration)
            log.info(
                "http_request_completed",
                method=request.method,
                route=route,
                status=status_code,
                duration_ms=round(duration * 1000, 2),
            )
            if response is not None:
                response.headers["x-request-id"] = request_id
            structlog.contextvars.clear_contextvars()

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(tenant.router, prefix="/api/v1")
    app.include_router(leads.router, prefix="/api/v1")
    app.include_router(guest_access.router, prefix="/api/v1")
    app.include_router(orders.router, prefix="/api/v1")
    app.include_router(webhooks.router, prefix="/api/v1")
    app.include_router(organisations.router, prefix="/api/v1")
    app.include_router(licence.router, prefix="/api/v1")
    app.include_router(subscriptions.router, prefix="/api/v1")
    app.include_router(catalogue.router, prefix="/api/v1")
    app.include_router(courses.router, prefix="/api/v1")
    app.include_router(course_wizard.router, prefix="/api/v1")
    app.include_router(learning_paths.router, prefix="/api/v1")
    app.include_router(workshops.router, prefix="/api/v1")
    app.include_router(deals.router, prefix="/api/v1")
    app.include_router(campaigns.router, prefix="/api/v1")
    app.include_router(learning.router, prefix="/api/v1")
    app.include_router(media.router, prefix="/api/v1")
    app.include_router(assessment.router, prefix="/api/v1")
    app.include_router(credentials.router, prefix="/api/v1")
    app.include_router(podcasts.router, prefix="/api/v1")
    app.include_router(articles.router, prefix="/api/v1")
    app.include_router(recommendations.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(push.router, prefix="/api/v1")
    app.include_router(privacy.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    # Same /analytics prefix, same analytics:view gate — split into its own
    # module because operations reads join half the domain models and would
    # have doubled the revenue router's size (see its docstring).
    app.include_router(operations.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(invoices.router, prefix="/api/v1")
    app.include_router(tenant_users.router, prefix="/api/v1")
    app.include_router(tenant_branding.router, prefix="/api/v1")
    app.include_router(sso.router, prefix="/api/v1")
    app.include_router(platform.router, prefix="/api/v1")

    return app


app = create_app()

__all__ = ["app", "create_app"]
