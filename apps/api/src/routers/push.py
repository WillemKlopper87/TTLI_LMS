"""Web Push subscription management (01 §5.9). Every route here is
`PrincipalDep`-gated but needs no special permission beyond being
authenticated — subscribing/unsubscribing your own browser, and reading
the (public, non-secret) VAPID public key needed to call
`PushManager.subscribe()`, are self-service actions, not admin ones.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import PrincipalDep, SessionDep, SettingsDep
from src.core.errors import NotFound
from src.schemas.push import (
    PushSubscribeRequest,
    PushSubscriptionResponse,
    VapidPublicKeyResponse,
)
from src.services import push as push_service

router = APIRouter(tags=["push"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


@router.get("/push/vapid-public-key", response_model=VapidPublicKeyResponse)
async def get_vapid_public_key(settings: SettingsDep) -> VapidPublicKeyResponse:
    if not settings.vapid_public_key:
        return VapidPublicKeyResponse(configured=False)
    return VapidPublicKeyResponse(configured=True, public_key=settings.vapid_public_key)


@router.post(
    "/push-subscriptions",
    response_model=PushSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_push_subscription(
    body: PushSubscribeRequest, principal: PrincipalDep, session: SessionDep
) -> PushSubscriptionResponse:
    subscription = await push_service.subscribe(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        endpoint=body.endpoint,
        p256dh_key=body.keys.p256dh,
        auth_key=body.keys.auth,
    )
    return PushSubscriptionResponse(id=str(subscription.id))


@router.delete(
    "/push-subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_push_subscription(
    subscription_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    await push_service.unsubscribe(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        subscription_id=_parse_uuid(subscription_id),
    )


__all__ = ["router"]
