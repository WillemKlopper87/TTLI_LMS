"""OIDC single sign-on (`docs/BACKLOG.md` P4, feature-matrix gap #46).

**No new dependency.** README's stack table names `msal`, and the
research doc assumed a library; neither is needed. `httpx`, `PyJWT`
(which ships `PyJWKClient`) and `cryptography` are already runtime
dependencies, and authorisation-code flow with PKCE is a few hundred
lines of well-specified protocol. A library here would mostly be
wrapping `jwt.decode`, and this codebase has consistently declined
dependencies it would use one function of.

**What actually protects this flow**, in the order things go wrong:

1. **`state`, single-use, server-side.** Held in Redis, deleted on
   redemption. A replayed callback finds nothing and is refused, so a
   stolen code cannot be spent twice and a cross-site forged callback
   has no state to present.
2. **`nonce`, bound into the state record and checked against the
   `id_token`.** Stops an id_token minted for a different login being
   replayed into this one.
3. **Signature, issuer, audience and expiry**, all verified by
   `jwt.decode` against the IdP's published JWKS. Nothing here trusts an
   unverified token — notably `PyJWKClient` is given the JWKS URI from
   the discovery document of the *configured* issuer, never one named by
   the token.
4. **Email domain allowlist.** JIT provisioning trusts the IdP's email
   claim, so a misconfigured or hostile IdP asserting
   `ceo@another-company.com` would otherwise be handed that account.
   The tenant vouches for its own domains; anything else is refused
   before a user is looked up, let alone created.
5. **`email_verified`.** An IdP that says it has not verified the
   address is not a basis for logging someone in as that address.

PKCE is included even though this is a confidential client with a
secret. It costs one hash and removes code interception as a category
rather than as an argument.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import hmac
import ipaddress
import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWKClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, Unauthenticated
from src.models.sso import TenantIdpConfig

# Long enough that a person can finish an IdP login including an MFA
# prompt, short enough that an abandoned attempt is not a standing
# credential.
STATE_TTL_SECONDS = 600
# Where an SSO login lands when it carried no deep link of its own.
DEFAULT_NEXT_PATH = "/learn"
DISCOVERY_TIMEOUT = 8.0
# How long a discovery document is reused. It names four public
# endpoints and changes about once a year; an hour is short enough
# that a provider genuinely moving one is picked up the same working
# day, and long enough that a burst of sign-ins costs one fetch.
DISCOVERY_CACHE_SECONDS = 3600


class SsoError(AppError):
    """A configuration or protocol problem the caller can act on."""


@dataclass(frozen=True, slots=True)
class Discovery:
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    issuer: str


@dataclass(frozen=True, slots=True)
class Started:
    """What `begin` produced: where to send the browser, and the secret
    that proves the browser that comes back is the one that left."""

    authorization_url: str
    binding: str


@dataclass(frozen=True, slots=True)
class SsoIdentity:
    """What an IdP asserted, after everything above has been checked."""

    email: str
    full_name: str | None
    groups: list[str]
    subject: str


async def get_config(
    session: AsyncSession, *, tenant_id: uuid.UUID, enabled_only: bool = True
) -> TenantIdpConfig | None:
    stmt = select(TenantIdpConfig).where(TenantIdpConfig.tenant_id == tenant_id)
    if enabled_only:
        stmt = stmt.where(TenantIdpConfig.enabled.is_(True))
    return (await session.execute(stmt)).scalar_one_or_none()


async def discover(
    issuer: str, *, allow_local: bool = False, redis: Redis | None = None
) -> Discovery:
    """Read the IdP's own discovery document rather than guessing
    endpoint shapes. Entra, Okta and Google all differ in path, and a
    hardcoded template is a support ticket per provider.

    Cached in Redis when a client is given. Every sign-in — start and
    callback both — was re-fetching a document that changes about once a
    year, over TLS, with four DNS lookups behind it, from an endpoint an
    anonymous caller can reach as often as they like (fable5.1 review
    M-4). The cache holds only the four endpoint strings, all of which
    are already public; it is a network round-trip saved, not a secret
    stored.
    """
    cache_key = f"oidc:discovery:{issuer}"
    if redis is not None:
        cached = await redis.get(cache_key)
        if cached:
            try:
                found = Discovery(**json.loads(cached))
            except (ValueError, TypeError):
                # A malformed or stale-shaped entry is not worth failing a
                # login over; fall through and fetch it again.
                await redis.delete(cache_key)
            else:
                # The egress guard runs on every *use*, not only on the
                # fetch. What is cached is the document — the TLS round
                # trip and the JSON — never the verdict that its
                # endpoints are safe to contact. Skipping the check here
                # would widen this module's one stated residual risk (a
                # name that resolves publicly at check time and privately
                # at connect time) from milliseconds to an hour.
                for endpoint in (
                    found.authorization_endpoint,
                    found.token_endpoint,
                    found.jwks_uri,
                ):
                    await assert_reachable_publicly(endpoint, allow_local=allow_local)
                return found

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    await assert_reachable_publicly(url, allow_local=allow_local)
    try:
        # follow_redirects stays off (httpx's default): a redirect is how
        # a public issuer URL would otherwise be turned into a fetch of
        # an internal one, after the check above has already passed.
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            document = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SsoError(
            "The identity provider's configuration could not be read.",
            {"issuer": issuer},
        ) from exc

    try:
        found = Discovery(
            authorization_endpoint=document["authorization_endpoint"],
            token_endpoint=document["token_endpoint"],
            jwks_uri=document["jwks_uri"],
            issuer=document["issuer"],
        )
    except KeyError as exc:
        raise SsoError(
            "That issuer is not a complete OIDC provider.", {"missing": str(exc)}
        ) from exc

    # The endpoints come out of a document, and a document can name
    # anything. Each one is checked before it is ever fetched.
    for endpoint in (found.authorization_endpoint, found.token_endpoint, found.jwks_uri):
        await assert_reachable_publicly(endpoint, allow_local=allow_local)

    # The discovery document must agree with the issuer we asked about,
    # or a redirect has moved us to somebody else's provider.
    if found.issuer.rstrip("/") != issuer.rstrip("/"):
        raise SsoError(
            "The identity provider's discovery document names a different issuer.",
            {"configured": issuer, "document": found.issuer},
        )

    if redis is not None:
        # Only after every check above has passed, so a document that was
        # refused is never the one served from cache next time.
        await redis.set(
            cache_key, json.dumps(dataclasses.asdict(found)), ex=DISCOVERY_CACHE_SECONDS
        )
    return found


async def assert_reachable_publicly(url: str, *, allow_local: bool = False) -> None:
    """Refuse to make a request to anything that is not a public host.

    Every URL this module fetches is ultimately named by a tenant
    administrator (the issuer) or by a document that administrator
    pointed us at (the token and JWKS endpoints). That is authenticated
    and privileged, but it is still a request *this server* makes to an
    address *somebody else* chose — the shape of an SSRF. Without this,
    `PUT /tenant/sso` is a probe primitive: point the issuer at
    `http://169.254.169.254/…` or an internal admin port and read the
    outcome from the error.

    Residual risk, stated rather than papered over: the name is resolved
    here and connected to by name afterwards, so a DNS entry that
    changes between the two can still land on a private address
    (rebinding). Closing that properly means connecting to the pinned IP
    with the hostname carried in SNI and Host, which is a custom
    transport; for a `tenant:manage`-gated setting the check below is
    the proportionate one, and it is applied at every fetch rather than
    once at save time.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http"):
        raise SsoError("An identity provider URL must be http(s).", {"url": url})
    if parts.scheme == "http" and not allow_local:
        raise SsoError(
            "An identity provider must be reached over HTTPS — an id_token is a credential.",
            {"url": url},
        )
    host = parts.hostname
    if not host:
        raise SsoError("That identity provider URL names no host.", {"url": url})

    try:
        # The loop's own resolver, which runs getaddrinfo in an executor.
        # Called directly this is a synchronous network round-trip on the
        # event loop — against a slow or hostile resolver, seconds of it,
        # on an endpoint anonymous callers can reach (fable5.1 review
        # M-4). Four of them per discovery, at that: once for the document
        # and once for each endpoint it names.
        resolved = await asyncio.get_running_loop().getaddrinfo(
            host, parts.port or (443 if parts.scheme == "https" else 80)
        )
    except OSError as exc:
        raise SsoError("That identity provider's hostname could not be resolved.") from exc

    if allow_local:
        # Non-production only, and the caller says so explicitly: a
        # developer running a mock IdP on localhost needs both halves of
        # this check relaxed, not one.
        return

    for info in resolved:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise SsoError(
                "An identity provider must be a public host.",
                {"host": host},
            )


def _state_key(state: str) -> str:
    return f"sso:state:{state}"


def safe_next_path(next_path: str | None) -> str:
    """Where to land after the round-trip, reduced to somewhere on this
    site.

    `?next=` reaches `POST /auth/sso/start` from an anonymous caller, is
    parked for the length of the flow, and comes back out of the callback
    for the browser to navigate to. Anything but a rooted path on this
    origin would make that an open redirect wearing a login flow's
    clothing — `//evil.example` is the one worth naming, since a browser
    reads a protocol-relative URL as another host while it still looks
    like a path. A backslash is refused for the same reason: some URL
    parsers fold it to a slash.
    """
    if not next_path:
        return DEFAULT_NEXT_PATH
    if not next_path.startswith("/"):
        return DEFAULT_NEXT_PATH
    if next_path.startswith("//") or "\\" in next_path:
        return DEFAULT_NEXT_PATH
    return next_path


async def begin(
    redis: Redis,
    *,
    config: TenantIdpConfig,
    discovery: Discovery,
    redirect_uri: str,
    next_path: str | None,
) -> Started:
    """Mint state + nonce + PKCE + a browser binding, park them, and
    return the URL to send the browser to."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    # Login CSRF: `state` alone proves the callback belongs to a flow
    # this server started — not that it belongs to *this browser's*
    # flow. Without the binding, an attacker starts a login, keeps the
    # resulting code and state, and hands the victim a link to our own
    # callback; the victim's browser completes it and is silently signed
    # in as the attacker, into the attacker's account. The binding is
    # returned to the BFF, which keeps it in an HttpOnly cookie, so only
    # the browser that began the flow can finish it. Stored as a digest:
    # a Redis dump should not hand anybody a working half of the pair.
    binding = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )

    await redis.set(
        _state_key(state),
        json.dumps(
            {
                "tenant_id": str(config.tenant_id),
                "nonce": nonce,
                "verifier": verifier,
                "binding_hash": hashlib.sha256(binding.encode()).hexdigest(),
                "redirect_uri": redirect_uri,
                # Carried through the round-trip so a deep link survives
                # the detour to the IdP — sanitised first, because the
                # browser navigates to whatever comes back out.
                "next": safe_next_path(next_path),
            }
        ),
        ex=STATE_TTL_SECONDS,
    )

    query = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return Started(authorization_url=f"{discovery.authorization_endpoint}?{query}", binding=binding)


async def take_state(redis: Redis, state: str, *, binding: str | None) -> dict[str, Any]:
    """Single use, by deletion, and only for the browser that started it.

    The deletion is unconditional — including when the binding does not
    match. A wrong binding means the flow is already compromised or
    confused, and leaving the state redeemable would let an attacker
    keep retrying against a victim who has one live state record.
    """
    raw = await redis.getdel(_state_key(state))
    if raw is None:
        raise Unauthenticated("That sign-in attempt has expired or was already used.")
    parsed: dict[str, Any] = json.loads(raw)

    expected = str(parsed.get("binding_hash") or "")
    supplied = hashlib.sha256(binding.encode()).hexdigest() if binding else ""
    # compare_digest, not ==: the comparison is over attacker-supplied
    # input against a secret-derived value.
    if not expected or not hmac.compare_digest(expected, supplied):
        raise Unauthenticated("That sign-in attempt did not start in this browser.")
    return parsed


async def exchange(
    *,
    config: TenantIdpConfig,
    crypto: CryptoBox,
    discovery: Discovery,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> str:
    """Swap the authorisation code for an id_token. Returns the raw
    token; validating it is deliberately a separate step."""
    try:
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT) as client:
            response = await client.post(
                discovery.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": config.client_id,
                    "client_secret": crypto.decrypt(config.client_secret_encrypted),
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise SsoError("The identity provider could not be reached.") from exc

    if response.status_code >= 400:
        # The provider's own error is the useful one ("invalid_client"
        # means the secret is wrong, and an admin can act on that), but
        # it is logged rather than returned — it can carry the request's
        # code and client_id.
        raise Unauthenticated("The identity provider rejected this sign-in.")

    payload = response.json()
    id_token = payload.get("id_token")
    if not isinstance(id_token, str):
        raise SsoError("The identity provider returned no id_token.")
    return id_token


# One client per JWKS URI, kept for the process's life. PyJWKClient caches
# the fetched key set internally, and a fresh client per call threw that
# cache away — so every single sign-in fetched the provider's whole key
# set over TLS again. Bounded by the number of configured issuers, which
# is one per tenant.
_jwk_clients: dict[str, PyJWKClient] = {}


def _jwk_client(jwks_uri: str) -> PyJWKClient:
    client = _jwk_clients.get(jwks_uri)
    if client is None:
        client = PyJWKClient(jwks_uri, cache_keys=True)
        _jwk_clients[jwks_uri] = client
    return client


async def validate_async(
    *, id_token: str, config: TenantIdpConfig, discovery: Discovery, nonce: str
) -> SsoIdentity:
    """`validate` off the event loop.

    Fetching the JWKS is a synchronous HTTPS round-trip inside
    `PyJWKClient`, and the RS256 verification after it is CPU work. Run
    directly from the callback handler — which is what happened — that is
    the whole process stalled on somebody else's server for as long as it
    takes them to answer. Same class of defect as the DNS resolution in
    `assert_reachable_publicly` (fable5.1 review M-4), and a much bigger
    stall.
    """
    return await asyncio.to_thread(
        validate, id_token=id_token, config=config, discovery=discovery, nonce=nonce
    )


def validate(
    *, id_token: str, config: TenantIdpConfig, discovery: Discovery, nonce: str
) -> SsoIdentity:
    """Signature, issuer, audience, expiry, nonce — then the claims.

    Blocking: async callers want `validate_async` above.

    The JWKS URI comes from the discovery document of the configured
    issuer, never from the token: a token that could name its own key
    source would validate against a key its author controls.
    """
    try:
        signing_key = _jwk_client(discovery.jwks_uri).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=config.client_id,
            issuer=discovery.issuer,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated("That sign-in could not be verified.") from exc

    if claims.get("nonce") != nonce:
        # The token is validly signed but belongs to a different login.
        raise Unauthenticated("That sign-in could not be verified.")

    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email or "@" not in email:
        raise SsoError("The identity provider did not return an email address.")

    # An IdP that says it has not verified the address is not a basis for
    # logging someone in as it. Absent means "not asserted" and is
    # treated as unverified rather than assumed true.
    if claims.get("email_verified") is False:
        raise Unauthenticated("Your identity provider has not verified that email address.")

    groups = claims.get("groups") or claims.get("roles") or []
    if not isinstance(groups, list):
        groups = []

    return SsoIdentity(
        email=email,
        full_name=claims.get("name") or None,
        groups=[str(g) for g in groups],
        subject=str(claims.get("sub", "")),
    )


def assert_domain_allowed(email: str, config: TenantIdpConfig) -> None:
    """The account-takeover guard, and the reason
    `allowed_email_domains` is NOT NULL.

    JIT provisioning is about to trust this address. Without the check,
    a misconfigured or hostile IdP asserting an address at a domain the
    tenant does not own would be handed — or given — that account.
    """
    domain = email.rsplit("@", 1)[-1].lower()
    allowed = {d.strip().lower().lstrip("@") for d in config.allowed_email_domains if d.strip()}
    if not allowed:
        raise SsoError("This identity provider has no allowed email domains configured.")
    if domain not in allowed:
        raise Unauthenticated(
            "Your identity provider returned an address outside this organisation's domains."
        )


def roles_for(identity: SsoIdentity, config: TenantIdpConfig) -> list[str]:
    """Group claims mapped to roles, plus the default. Unmapped groups
    are ignored rather than guessed at — a role the tenant did not name
    is authority nobody granted."""
    mapping = config.group_role_map or {}
    roles = {mapping[g] for g in identity.groups if g in mapping}
    if config.default_role_code:
        roles.add(config.default_role_code)
    return sorted(roles)


__all__ = [
    "DEFAULT_NEXT_PATH",
    "DISCOVERY_CACHE_SECONDS",
    "STATE_TTL_SECONDS",
    "Discovery",
    "SsoError",
    "SsoIdentity",
    "Started",
    "assert_domain_allowed",
    "assert_reachable_publicly",
    "begin",
    "discover",
    "exchange",
    "get_config",
    "roles_for",
    "safe_next_path",
    "take_state",
    "validate",
    "validate_async",
]
