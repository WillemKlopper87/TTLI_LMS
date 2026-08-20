"""`Idempotency-Key` handling (03 §1.6): "The key plus a hash of the
request body is stored; a replay with the same key and body returns the
original response, and a replay with the same key and a *different* body
returns `409`."

Implemented as HTTP middleware (`app.middleware("http")`, the same
mechanism `main.py`'s existing `request_context` middleware uses) rather
than a FastAPI dependency — a dependency runs *inside* route handling,
after the body is already being parsed, which is too late to intercept a
replay before the handler's own side effects run. Middleware wraps the
whole request/response cycle, so it can short-circuit before `call_next`
on a replay, and inspect the final response no matter which layer
produced it (a 2xx from the handler, or a deliberately raised `AppError`
already shaped into a response by `app_error_handler` further down the
stack).

`SCOPED_ROUTES` limits enforcement to the handful of endpoints 03 §1.6
actually names: `POST /orders`, `POST /payments/{id}/approve`, `POST
/payments/{id}/reject`, `POST /orders/{id}/refund`. `POST
/orders/{id}/checkout/card` and the Payfast webhook exist now (03 §5.2/
§5.7) but were never named by §1.6 for idempotency, so this list correctly
didn't grow when they landed — a browser retry there is a second Payfast
redirect the buyer just gets to abandon, and Payfast's own `provider_event_
id` uniqueness (`payment_webhooks`) is what makes the webhook replay-safe
instead. This is not the ceiling of what idempotency *could* cover, only
what has a real caller today.

Definitive vs transient: a response below 500 is cached and replayed
verbatim on a retry — that includes a deliberate refusal (403, 404, a
business-rule 400), which is still "the original response" the spec asks
for. A 5xx is never cached, so a genuinely failed attempt (a dead DB
connection, an unhandled bug) leaves the key retryable rather than
permanently poisoning it with a transient failure.

Concurrency (0032): the key row is INSERTed as an in-flight reservation
(`response_status` NULL, `ON CONFLICT DO NOTHING` against the scope's
unique index) *before* the handler runs, and UPDATEd with the response
after. Two simultaneous replays therefore serialise at the index: one
executes, the other gets a 409 `IDEMPOTENCY_REPLAY_IN_FLIGHT` (retry
shortly and receive the cached result) instead of a second execution.
A reservation whose process died without recording a response is taken
over once it is older than STALE_RESERVATION, and the worker's nightly
sweep (`prune_idempotency_keys`) removes both completed rows past their
retention window and any dead reservations that path missed.

Tenant/user scoping comes from decoding the caller's own JWT directly
(`decode_access_token`), not from re-running `get_tenant`/`get_principal`'s
full resolution — this middleware only needs `tid`/`sub` to key a storage
lookup, not to make an authorisation decision. If the token is missing,
expired, or doesn't decode, idempotency handling is simply skipped and the
request proceeds to the real route, whose own `PrincipalDep` performs the
real check (including the host-vs-token tenant cross-check) and 401/403s
correctly — this middleware never weakens that, it only sometimes declines
to add replay protection on top of it.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable

import jwt
import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from starlette.requests import Request
from starlette.responses import Response

from src.core.config import get_settings
from src.core.db import tenant_session
from src.core.errors import error_envelope
from src.core.ids import uuid7
from src.core.security import decode_access_token
from src.models.idempotency import IdempotencyKey

log = structlog.get_logger(__name__)

HEADER = "idempotency-key"

# A reservation older than this whose response never arrived is treated as
# dead (the process crashed between the handler's commit and the response
# UPDATE, or mid-handler) and may be taken over by a retry. Generous
# relative to any real handler runtime, so a live first attempt is never
# usurped while it is still executing.
STALE_RESERVATION = "5 minutes"

# (method, compiled path pattern). Matched against request.url.path, which
# at the middleware layer is the raw path — no route params have been
# resolved yet, hence regexes rather than FastAPI's own path templates.
SCOPED_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/api/v1/orders$")),
    ("POST", re.compile(r"^/api/v1/orders/[^/]+/refund$")),
    ("POST", re.compile(r"^/api/v1/payments/[^/]+/approve$")),
    ("POST", re.compile(r"^/api/v1/payments/[^/]+/reject$")),
)


def _scoped(method: str, path: str) -> bool:
    return any(method == m and pattern.match(path) for m, pattern in SCOPED_ROUTES)


def _principal_from_bearer(request: Request) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Best-effort (tenant_id, user_id) from the Authorization header, or
    None if it's missing/invalid — see the module docstring for why that's
    the correct fallback rather than an error here."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        claims = decode_access_token(header[7:].strip(), secret=get_settings().secret_key)
        return uuid.UUID(claims["tid"]), uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


async def idempotency_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if not _scoped(request.method, request.url.path):
        return await call_next(request)

    principal = _principal_from_bearer(request)
    if principal is None:
        return await call_next(request)
    tenant_id, user_id = principal

    key = request.headers.get(HEADER)
    if not key:
        return error_envelope(
            code="IDEMPOTENCY_KEY_REQUIRED",
            message="This endpoint requires an Idempotency-Key header.",
            details={},
            request=request,
            status_code=400,
        )

    # Reading the body here does not deny it to the route handler below —
    # Starlette's Request caches it on first read and replays the cached
    # bytes to every subsequent .body()/.json() call, including the
    # handler's own pydantic parsing.
    raw_body = await request.body()
    request_hash = hashlib.sha256(raw_body).hexdigest()

    # Reserve the key BEFORE running the handler. The unique index
    # `uq_idempotency_keys_scope` is what serialises two concurrent
    # replays: exactly one INSERT wins; the loser sees the winner's row
    # and never reaches the handler. Storing the key only *after* the
    # handler (as this middleware originally did) let both replays miss
    # the lookup, both execute the side effect, and the loser then 500
    # on the index — with its duplicate order already committed.
    reservation_id = uuid7()
    async with tenant_session(tenant_id) as session:
        won = (
            await session.execute(
                pg_insert(IdempotencyKey)
                .values(
                    id=reservation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    idempotency_key=key,
                    path=request.url.path,
                    request_hash=request_hash,
                    response_status=None,
                    response_body=None,
                )
                .on_conflict_do_nothing(
                    index_elements=["tenant_id", "user_id", "idempotency_key", "path"]
                )
                .returning(IdempotencyKey.id)
            )
        ).scalar_one_or_none()

        if won is None:
            existing = (
                await session.execute(
                    select(IdempotencyKey).where(
                        IdempotencyKey.tenant_id == tenant_id,
                        IdempotencyKey.user_id == user_id,
                        IdempotencyKey.idempotency_key == key,
                        IdempotencyKey.path == request.url.path,
                    )
                )
            ).scalar_one()

            if existing.request_hash != request_hash:
                return error_envelope(
                    code="IDEMPOTENCY_KEY_CONFLICT",
                    message="This Idempotency-Key was already used with a different request body.",
                    details={},
                    request=request,
                    status_code=409,
                )

            if existing.response_status is None:
                # In-flight. If the reservation is fresh, the first
                # attempt is still executing — tell the caller to retry,
                # never run the handler a second time concurrently. If it
                # is stale, its process died without recording a response
                # (or releasing the row): take the reservation over and
                # execute, which is exactly what a retry is for.
                taken_over = (
                    await session.execute(
                        sa_update(IdempotencyKey)
                        .where(
                            IdempotencyKey.id == existing.id,
                            IdempotencyKey.response_status.is_(None),
                            IdempotencyKey.created_at
                            < sa_func.now() - sa_text(f"interval '{STALE_RESERVATION}'"),
                        )
                        .values(created_at=sa_func.now())
                        .returning(IdempotencyKey.id)
                    )
                ).scalar_one_or_none()
                if taken_over is None:
                    return error_envelope(
                        code="IDEMPOTENCY_REPLAY_IN_FLIGHT",
                        message=(
                            "The original request with this Idempotency-Key is still "
                            "being processed. Retry shortly to receive its result."
                        ),
                        details={},
                        request=request,
                        status_code=409,
                    )
                log.warning("idempotency_stale_reservation_taken_over", path=request.url.path)
                reservation_id = existing.id
            else:
                return Response(
                    content=(
                        json.dumps(existing.response_body)
                        if existing.response_body is not None
                        else b""
                    ),
                    status_code=existing.response_status,
                    media_type="application/json" if existing.response_body is not None else None,
                )

    # Reservation held: run the real handler. call_next's response wraps a
    # one-shot body_iterator, so it has to be drained and a fresh Response
    # built from the buffered bytes before it can both be stored and
    # actually sent — the standard read-and-replay pattern for
    # @app.middleware("http"), the same reason request_context's simpler
    # pass-through above never needed to touch the body at all.
    try:
        response = await call_next(request)
        body_chunks = [chunk async for chunk in response.body_iterator]  # type: ignore[attr-defined]
        body = b"".join(body_chunks)
    except Exception:
        # The handler never produced a response (the error handlers further
        # down the stack normally shape even a bug into a 500, so this is
        # rare — a cancelled request, a truly broken middleware below).
        # Release the reservation so the key stays retryable.
        await _release_reservation(tenant_id, reservation_id)
        raise

    headers = dict(response.headers)
    headers.pop("content-length", None)
    rebuilt = Response(content=body, status_code=response.status_code, headers=headers)

    parsed_body: dict[str, object] | list[object] | None = None
    parseable = True
    if body:
        try:
            parsed_body = json.loads(body)
        except json.JSONDecodeError:
            # Every scoped endpoint returns JSON or 204 — this is a
            # defensive fallback for something that should not happen,
            # not a designed path. Logged, and the reservation released
            # rather than caching something that couldn't be replayed
            # correctly anyway; the caller still gets its real response.
            log.warning("idempotency_response_not_json", path=request.url.path)
            parseable = False

    if response.status_code >= 500 or not parseable:
        # Transient failure: never cache it, and release the key so a
        # retry can re-execute rather than being told "in flight" until
        # the stale-reservation window opens.
        await _release_reservation(tenant_id, reservation_id)
        return rebuilt

    async with tenant_session(tenant_id) as session:
        await session.execute(
            sa_update(IdempotencyKey)
            .where(IdempotencyKey.id == reservation_id)
            .values(response_status=response.status_code, response_body=parsed_body)
        )

    return rebuilt


async def _release_reservation(tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> None:
    try:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                sa_delete(IdempotencyKey).where(
                    IdempotencyKey.id == reservation_id,
                    IdempotencyKey.response_status.is_(None),
                )
            )
    except Exception:  # releasing is best-effort by design
        # If the DB is the thing that is down, the reservation cannot be
        # released now; the stale-reservation window (and the worker's
        # sweep) reclaims it. The caller's real response/error must not
        # be replaced by this cleanup failing.
        log.warning("idempotency_release_failed", reservation_id=str(reservation_id))


__all__ = ["idempotency_middleware"]
