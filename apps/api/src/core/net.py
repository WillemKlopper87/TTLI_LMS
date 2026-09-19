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

import asyncio
import ipaddress

from starlette.requests import Request


def client_ip(request: Request, *, trust_x_forwarded_for: bool) -> str | None:
    if trust_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


async def resolve_addresses(host: str, port: int) -> list[str]:
    """Thin wrapper around the event loop's own resolver (`getaddrinfo`
    runs in an executor, not blocking the loop directly), so a caller
    testing the guard below can substitute a fake resolver instead of
    depending on live DNS — "a test that needs a resolver is a test
    that fails on a train" (tests/test_sso.py). Raises OSError if `host`
    cannot be resolved."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port)
    return [info[4][0] for info in infos]


async def assert_public_hostname(host: str, port: int) -> None:
    """Resolve `host` and refuse if any resolved address is private,
    loopback, link-local, reserved, multicast or unspecified.

    The same check `services/oidc.py::assert_reachable_publicly` already
    applies to SSO issuer URLs, extracted here so any other server-side
    fetch of a caller-chosen host (currently `services/push.py::subscribe`)
    can apply it too. A pure string/IP-literal check is not enough: a
    hostname an attacker controls resolves to 169.254.169.254 or an
    internal address exactly as easily as a disallowed literal typed
    directly into the URL (DNS rebinding) — this is what actually closes
    that gap, at the cost of the same residual the oidc.py docstring
    already states: the name is resolved here and connected to by name
    afterwards, so a record that changes between the two can still land
    on a private address. Raises ValueError, not this module's own
    exception type, so each caller can wrap it in whatever error shape
    its endpoint already uses.
    """
    try:
        addresses = await resolve_addresses(host, port)
    except OSError as exc:
        raise ValueError(f"{host!r} could not be resolved.") from exc
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValueError(f"{host!r} resolves to a non-public address.")


__all__ = ["assert_public_hostname", "client_ip", "resolve_addresses"]
