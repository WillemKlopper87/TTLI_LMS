from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from pydantic import BaseModel, field_validator


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


def _validate_push_endpoint(value: str) -> str:
    """The endpoint is a URL the *worker* will later POST to on the
    client's say-so — a server-side request to a client-chosen address,
    i.e. an SSRF surface unless constrained. Every real push service
    (FCM, WNS, Mozilla autopush, APNs web push) hands out an `https://`
    URL on a public hostname, so anything else is refused: plain http,
    IP literals (loopback/link-local/metadata/private ranges included),
    `localhost`, and reserved single-label/internal suffixes. The list
    is deliberately a *deny* of the shapes that only make sense as an
    attack, not an allow-list of known push-service domains — Brave/
    Opera/Samsung/Vivaldi all ride other vendors' services and a fixed
    allow-list would silently break real browsers.
    """
    parts = urlsplit(value)
    if parts.scheme != "https":
        raise ValueError("Push endpoint must be an https:// URL.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or parts.username or parts.password:
        raise ValueError("Push endpoint must have a plain hostname.")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise ValueError("Push endpoint must use a hostname, not an IP address.")
    if host == "localhost" or "." not in host:
        raise ValueError("Push endpoint must be a public hostname.")
    if host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".arpa")):
        raise ValueError("Push endpoint must be a public hostname.")
    return value


class PushSubscribeRequest(BaseModel):
    """The shape `PushSubscription.toJSON()` already produces in the
    browser — passed straight through, not reshaped, beyond the endpoint
    check above."""

    endpoint: str
    keys: PushSubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def _endpoint_is_public_https(cls, value: str) -> str:
        return _validate_push_endpoint(value)


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
