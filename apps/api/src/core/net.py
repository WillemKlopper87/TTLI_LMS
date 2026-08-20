"""Client-address resolution behind the BFF.

Every browser request reaches this API through the Next.js BFF, so
`request.client.host` is the BFF's address for all of them — which
quietly turned every per-IP rate limit (login, leads, guest access,
credential verification) into ONE shared bucket for the whole site: a
single abuser could exhaust it for every legitimate visitor, and no
limit ever distinguished two browsers.

The BFF now forwards `X-Forwarded-For` (its own server populates it
from the socket), and this helper honours it — but only when
`TRUST_X_FORWARDED_FOR` says the deployment guarantees the API is
reachable exclusively through that trusted proxy. Enabled without that
guarantee, any direct caller could spoof the header and dodge every
per-IP limit, which is why the flag defaults to False and is a
deployment decision, not a code default.

The first address in the list is used: with exactly one trusted proxy
(the BFF, which OVERWRITES rather than appends, mirroring its
X-Tenant-Host stance), that is the address the proxy itself observed.
"""

from __future__ import annotations

from starlette.requests import Request


def client_ip(request: Request, *, trust_x_forwarded_for: bool) -> str | None:
    if trust_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


__all__ = ["client_ip"]
