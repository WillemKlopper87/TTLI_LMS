"""One error envelope, used by every non-2xx response.

    {"error": {"code": ..., "message": ..., "details": {...}, "request_id": ...}}

Messages never disclose whether an email address exists, which tenant a resource
belongs to, or why authorisation failed beyond the fact that it did.

`error_envelope` is public (not the originally private `_envelope`)
specifically so `core/idempotency.py`'s middleware can build the same
shape for its own 400/409 responses — those are emitted from outside the
exception-handler machinery below (the middleware short-circuits before
`call_next`, so no `AppError` is ever raised to route through
`app_error_handler`), and a second, differently-shaped error body from the
same API would be a real, visible inconsistency, not just an internal
tidiness concern.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base for every error this application raises deliberately."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class Unauthenticated(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class TenantUnresolved(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "TENANT_UNRESOLVED"


class LessonLocked(AppError):
    status_code = status.HTTP_423_LOCKED
    code = "LESSON_LOCKED"


class TooManyAttempts(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "TOO_MANY_ATTEMPTS"


class ServiceUnavailable(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"


def error_envelope(
    *, code: str, message: str, details: dict[str, Any], request: Request, status_code: int
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                    "request_id": request_id,
                }
            }
        ),
    )


# Starlette types every handler as taking a bare Exception, so each one narrows
# to the type it was registered for. cast rather than assert: an assert here
# would be compiled away under -O and is flagged as a security smell.
async def app_error_handler(request: Request, raw: Exception) -> JSONResponse:
    exc = cast(AppError, raw)
    return error_envelope(
        code=exc.code,
        message=exc.message,
        details=exc.details,
        request=request,
        status_code=exc.status_code,
    )


async def http_error_handler(request: Request, raw: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, raw)
    codes = {
        400: "BAD_REQUEST",
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "RATE_LIMITED",
    }
    return error_envelope(
        code=codes.get(exc.status_code, "ERROR"),
        message=str(exc.detail),
        details={},
        request=request,
        status_code=exc.status_code,
    )


async def validation_error_handler(request: Request, raw: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, raw)
    return error_envelope(
        code="VALIDATION_FAILED",
        message="The request body did not validate.",
        details={"errors": exc.errors()},
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


__all__ = [
    "AppError",
    "Forbidden",
    "LessonLocked",
    "NotFound",
    "ServiceUnavailable",
    "TenantUnresolved",
    "TooManyAttempts",
    "Unauthenticated",
    "app_error_handler",
    "error_envelope",
    "http_error_handler",
    "validation_error_handler",
]
