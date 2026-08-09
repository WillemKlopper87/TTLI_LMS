"""Application entry point."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

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
from src.core.logging import configure_logging, get_logger
from src.core.redis import dispose_redis, init_redis
from src.routers import auth, health

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

    init_engine(settings)
    init_redis(settings)
    log.info("api_started", environment=settings.environment)
    yield
    await dispose_engine()
    await dispose_redis()


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

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = request_id
        return response

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")

    return app


app = create_app()

__all__ = ["app", "create_app"]
