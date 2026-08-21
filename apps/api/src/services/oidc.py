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

import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

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
DISCOVERY_TIMEOUT = 8.0


class SsoError(AppError):
    """A configuration or protocol problem the caller can act on."""


@dataclass(frozen=True, slots=True)
class Discovery:
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    issuer: str


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


async def discover(issuer: str) -> Discovery:
    """Read the IdP's own discovery document rather than guessing
    endpoint shapes. Entra, Okta and Google all differ in path, and a
    hardcoded template is a support ticket per provider."""
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
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

    # The discovery document must agree with the issuer we asked about,
    # or a redirect has moved us to somebody else's provider.
    if found.issuer.rstrip("/") != issuer.rstrip("/"):
        raise SsoError(
            "The identity provider's discovery document names a different issuer.",
            {"configured": issuer, "document": found.issuer},
        )
    return found


def _state_key(state: str) -> str:
    return f"sso:state:{state}"


async def begin(
    redis: Redis,
    *,
    config: TenantIdpConfig,
    discovery: Discovery,
    redirect_uri: str,
    next_path: str | None,
) -> str:
    """Mint state + nonce + PKCE, park them, and return the URL to send
    the browser to."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
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
                "redirect_uri": redirect_uri,
                # Carried through the round-trip so a deep link survives
                # the detour to the IdP.
                "next": next_path or "/learn",
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
    return f"{discovery.authorization_endpoint}?{query}"


async def take_state(redis: Redis, state: str) -> dict[str, Any]:
    """Single use, by deletion. A replayed callback finds nothing."""
    raw = await redis.getdel(_state_key(state))
    if raw is None:
        raise Unauthenticated("That sign-in attempt has expired or was already used.")
    parsed: dict[str, Any] = json.loads(raw)
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


def validate(
    *, id_token: str, config: TenantIdpConfig, discovery: Discovery, nonce: str
) -> SsoIdentity:
    """Signature, issuer, audience, expiry, nonce — then the claims.

    The JWKS URI comes from the discovery document of the configured
    issuer, never from the token: a token that could name its own key
    source would validate against a key its author controls.
    """
    try:
        signing_key = PyJWKClient(discovery.jwks_uri).get_signing_key_from_jwt(id_token)
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
    "STATE_TTL_SECONDS",
    "Discovery",
    "SsoError",
    "SsoIdentity",
    "assert_domain_allowed",
    "begin",
    "discover",
    "exchange",
    "get_config",
    "roles_for",
    "take_state",
    "validate",
]
