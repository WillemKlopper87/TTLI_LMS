"""Web Push (01 §5.9) — three triggers, per the product owner's explicit
choice: payment approved/rejected, certificate/badge issued, and a
workshop-starting-soon reminder. VAPID is a self-generated keypair, not a
third party's credential:

    python -c "
    from py_vapid import Vapid02
    from cryptography.hazmat.primitives import serialization
    import base64
    v = Vapid02(); v.generate_keys()
    fmt = serialization.PublicFormat.UncompressedPoint
    pub = v.public_key.public_bytes(serialization.Encoding.X962, fmt)
    priv = v.private_key.private_numbers().private_value.to_bytes(32, 'big')
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    print('VAPID_PUBLIC_KEY=' + b64(pub)); print('VAPID_PRIVATE_KEY=' + b64(priv))
    "

`send_push_sync`/`notify_user` mirror `services/email.py`'s exact split:
a sync function meant to be called from inside the worker via
`asyncio.to_thread` (pywebpush's `webpush()` is a blocking `requests`
call, not an async one), and an async enqueue function that never raises
— an unreachable Redis must not fail the transaction that triggered the
notification.
"""

from __future__ import annotations

import json
import uuid

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.ids import uuid7
from src.core.logging import get_logger
from src.core.queue import get_queue
from src.models.push import PushSubscription

log = get_logger(__name__)

SEND_PUSH_JOB = "send_push_job"

# pywebpush defaults TTL to 0 ("deliver now or drop"), which WNS — the push
# service behind Edge on Windows — rejects outright with 400 "Ttl value
# conflicts with X-WNS-Cache-Policy" (found by the live smoke test; FCM and
# Mozilla accept 0). 24h matches the longest-lived trigger (workshop
# reminders fire 24h ahead) and lets a closed laptop still see "payment
# approved" when it wakes.
PUSH_TTL_SECONDS = 24 * 60 * 60


class PushSubscriptionGone(Exception):
    """The push service reports this endpoint no longer exists (404/410)
    — the browser subscription was revoked or expired. Not a delivery
    failure to retry; the caller (the worker job) should delete the row."""


def send_push_sync(
    settings: Settings,
    *,
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
    title: str,
    body: str,
    url: str | None,
) -> None:
    """Called by the worker job, not directly — exported for it to
    import, same convention `services/email.py::send_sync` established.
    Raises `PushSubscriptionGone` on a dead endpoint, `WebPushException`
    on anything else that failed — the caller decides what each means."""
    subscription_info = {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh_key, "auth": auth_key},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=PUSH_TTL_SECONDS,
        )
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            raise PushSubscriptionGone(str(exc)) from exc
        raise


async def subscribe(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
) -> PushSubscription:
    """Upserts on `endpoint` — re-subscribing the same device (a common
    browser behaviour when a subscription's keys rotate) replaces the row
    rather than accumulating dead duplicates."""
    existing = (
        await session.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    ).scalar_one_or_none()
    if existing is not None:
        existing.p256dh_key = p256dh_key
        existing.auth_key = auth_key
        existing.user_id = user_id
        await session.flush()
        return existing

    subscription = PushSubscription(
        id=uuid7(),
        tenant_id=tenant_id,
        user_id=user_id,
        endpoint=endpoint,
        p256dh_key=p256dh_key,
        auth_key=auth_key,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def unsubscribe(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, subscription_id: uuid.UUID
) -> None:
    subscription = await session.get(PushSubscription, subscription_id)
    if subscription is None or subscription.tenant_id != tenant_id:
        return
    if subscription.user_id != user_id:
        return
    await session.delete(subscription)
    await session.flush()


async def notify_user(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    body: str,
    url: str | None = None,
) -> None:
    """Enqueue delivery to every device this user has subscribed on.
    Never raises — same reasoning as `services/email.py::send_email`:
    an enqueue failure (Redis down) must not fail the order-approval/
    certificate-issuance transaction that triggered it."""
    subscriptions = (
        (
            await session.execute(
                select(PushSubscription.id).where(
                    PushSubscription.tenant_id == tenant_id, PushSubscription.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not subscriptions:
        return
    try:
        queue = get_queue()
        for subscription_id in subscriptions:
            await queue.enqueue_job(
                SEND_PUSH_JOB,
                tenant_id=str(tenant_id),
                subscription_id=str(subscription_id),
                title=title,
                body=body,
                url=url,
            )
    except Exception:
        log.error("push_enqueue_failed", user_id=str(user_id))


__all__ = [
    "PUSH_TTL_SECONDS",
    "SEND_PUSH_JOB",
    "PushSubscriptionGone",
    "notify_user",
    "send_push_sync",
    "subscribe",
    "unsubscribe",
]
