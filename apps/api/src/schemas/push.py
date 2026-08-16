from __future__ import annotations

from pydantic import BaseModel


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    """The shape `PushSubscription.toJSON()` already produces in the
    browser — passed straight through, not reshaped."""

    endpoint: str
    keys: PushSubscriptionKeys


class PushSubscriptionResponse(BaseModel):
    id: str


class VapidPublicKeyResponse(BaseModel):
    configured: bool
    public_key: str | None = None


__all__ = [
    "PushSubscribeRequest",
    "PushSubscriptionKeys",
    "PushSubscriptionResponse",
    "VapidPublicKeyResponse",
]
