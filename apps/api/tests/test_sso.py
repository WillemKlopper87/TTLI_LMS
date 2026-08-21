"""OIDC single sign-on (`routers/sso.py`, `services/oidc.py`, backlog P4).

These tests mint **real RS256 tokens against a real key pair** and let
the production code verify them through its normal path, rather than
monkeypatching `validate` and asserting the mock was called. A token
check that is never given a genuinely bad token has not been tested —
and the checks here (signature, issuer, audience, nonce, email domain)
are the entire security value of the feature.

The IdP itself is faked at the HTTP boundary: `discover` and `exchange`
are the two functions that leave the process, so a transport stub gives
the flow a provider to talk to without a network.
"""

from __future__ import annotations

import json
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.errors import Forbidden
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.models.rbac import RoleAssignment
from src.services import identity, oidc
from src.services import tenant_users as people

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"
PASSWORD = "correct horse battery staple 9!"
ISSUER = "https://idp.example.com"
CLIENT_ID = "ttli-test-client"
# What `routers/sso.callback_url` must derive for this tenant, given
# the default PUBLIC_WEB_URL of http://localhost:3010 outside production.
EXPECTED_REDIRECT = "http://localhost:3010/auth/sso/callback"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key-1"


def _redis_reachable(url: str) -> bool:
    parsed = urlparse(url)
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((parsed.hostname or "localhost", parsed.port or 6379))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _jwks() -> dict[str, Any]:
    numbers = _KEY.public_key().public_numbers()

    def b64(value: int) -> str:
        import base64

        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _KID,
                "use": "sig",
                "alg": "RS256",
                "n": b64(numbers.n),
                "e": b64(numbers.e),
            }
        ]
    }


def make_id_token(
    *,
    nonce: str,
    email: str = "person@allowed.example",
    issuer: str = ISSUER,
    audience: str = CLIENT_ID,
    email_verified: bool | None = True,
    groups: list[str] | None = None,
    key: Any = None,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": "idp-subject-1",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": nonce,
        "email": email,
        "name": "Test Person",
    }
    if email_verified is not None:
        claims["email_verified"] = email_verified
    if groups is not None:
        claims["groups"] = groups
    return jwt.encode(claims, key or _KEY, algorithm="RS256", headers={"kid": _KID})


class FakeIdp(httpx.AsyncBaseTransport):
    """Answers discovery, JWKS and the token endpoint. Everything else
    404s, so an unexpected outbound call fails loudly."""

    def __init__(self) -> None:
        self.id_token: str | None = None
        self.token_status = 200
        self.token_requests: list[dict[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if url.endswith("/jwks"):
            return httpx.Response(200, json=_jwks())
        if url.endswith("/token"):
            form = parse_qs(request.content.decode(), keep_blank_values=True)
            self.token_requests.append({k: v[0] for k, v in form.items()})
            if self.token_status >= 400:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token})
        return httpx.Response(404)


@pytest.fixture
def fake_idp(monkeypatch: pytest.MonkeyPatch) -> FakeIdp:
    idp = FakeIdp()
    real_client = httpx.AsyncClient

    def patched(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = idp
        return real_client(*args, **kwargs)

    # The egress guard is real-network machinery: it resolves the host
    # and refuses private addresses. `idp.example.com` does not resolve,
    # so leaving it in would make every flow test fail on DNS rather
    # than on anything about OIDC. It has its own tests below, against
    # literal addresses that need no resolver.
    monkeypatch.setattr(oidc, "assert_reachable_publicly", lambda url, **kw: None)
    # PyJWKClient fetches JWKS with urllib, not httpx, so it is pointed
    # at the same key material directly.
    monkeypatch.setattr(oidc.httpx, "AsyncClient", patched)
    monkeypatch.setattr(
        oidc,
        "PyJWKClient",
        lambda uri: _StubJwkClient(),
    )
    return idp


class _StubJwkClient:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        class _Key:
            key = _KEY.public_key()

        return _Key()


@pytest.fixture
async def client(settings, database_url):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip("no Redis on the configured REDIS_URL")
    init_engine(settings)
    redis = init_redis(settings)
    await redis.flushdb()
    await init_queue(settings)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.headers["X-Tenant-Host"] = TENANT_HOST
        yield c
    await dispose_engine()
    await dispose_redis()
    await dispose_queue()


def _unique_email() -> str:
    return f"sso-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _login(client, tenant_session_factory, crypto, *, tenant_id, role) -> str:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        if role:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role))
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _configure(client, token: str, **overrides: Any) -> None:
    body = {
        "display_name": "Sign in with Test IdP",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": "super-secret",
        "allowed_email_domains": ["allowed.example"],
        "group_role_map": {"finance-team": "finance"},
        "default_role_code": None,
        "enabled": True,
    }
    body.update(overrides)
    resp = await client.put(
        "/api/v1/tenant/sso", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text


async def _start(client) -> tuple[str, str, str]:
    """Begin a login and read back the state, nonce and browser binding
    the server minted."""
    resp = await client.post("/api/v1/auth/sso/start")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    params = parse_qs(urlparse(body["authorization_url"]).query)
    return params["state"][0], params["nonce"][0], body["binding"]


async def _callback(client, *, state: str, binding: str | None, code: str = "auth-code"):  # type: ignore[no-untyped-def]
    headers = {"X-Sso-Binding": binding} if binding is not None else {}
    return await client.post(
        "/api/v1/auth/sso/callback", json={"code": code, "state": state}, headers=headers
    )


async def test_sso_config_is_write_only_for_the_secret(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await _configure(client, boss)

    resp = await client.get("/api/v1/tenant/sso", headers={"Authorization": f"Bearer {boss}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["issuer"] == ISSUER
    # Not present, not masked. A field that can only be written is
    # clearer than one that returns asterisks.
    assert "client_secret" not in body
    assert "super-secret" not in json.dumps(body)

    # An anonymous caller learns only that SSO exists and what to label
    # the button — never the issuer or the domains.
    public = await client.get("/api/v1/auth/sso/available")
    assert public.status_code == 200
    assert public.json() == {"available": True, "display_name": "Sign in with Test IdP"}


async def test_a_valid_login_provisions_the_user_and_maps_group_roles(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    email = f"jit-{uuid.uuid4().hex[:8]}@allowed.example"
    await _configure(client, boss)

    state, nonce, binding = await _start(client)
    fake_idp.id_token = make_id_token(nonce=nonce, email=email, groups=["finance-team"])

    resp = await _callback(client, state=state, binding=binding)
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]

    # Provisioned with no password: the account exists only through the
    # IdP, so there is no second way in the tenant cannot revoke.
    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text("SELECT password_hash FROM users WHERE email_domain = 'allowed.example'")
            )
        ).first()
    assert row is not None and row[0] is None

    # PKCE really was sent, not just generated.
    assert fake_idp.token_requests[-1]["code_verifier"]


async def test_state_is_single_use(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp
) -> None:
    """A stolen authorisation code cannot be spent twice."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await _configure(client, boss)
    state, nonce, binding = await _start(client)
    fake_idp.id_token = make_id_token(nonce=nonce)

    first = await _callback(client, state=state, binding=binding, code="c")
    assert first.status_code == 200, first.text

    replay = await _callback(client, state=state, binding=binding, code="c")
    assert replay.status_code == 401

    forged = await _callback(client, state="never-issued", binding=binding, code="c")
    assert forged.status_code == 401


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"nonce": "a-different-nonce"}, "a token minted for another login"),
        ({"issuer": "https://evil.example.com"}, "a token from the wrong issuer"),
        ({"audience": "someone-elses-client"}, "a token for another audience"),
        ({"email_verified": False}, "an address the IdP has not verified"),
        ({"email": "ceo@another-company.com"}, "an address outside the allowed domains"),
    ],
)
async def test_a_token_that_fails_any_check_is_refused(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp, kwargs: dict[str, Any], reason: str
) -> None:
    """Each of these is a real, correctly-signed RS256 token that differs
    in exactly one claim — which is the only way to know the check runs
    rather than the mock agreeing with itself."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await _configure(client, boss)
    state, nonce, binding = await _start(client)

    token_args: dict[str, Any] = {"nonce": nonce}
    token_args.update(kwargs)
    fake_idp.id_token = make_id_token(**token_args)

    resp = await _callback(client, state=state, binding=binding, code="c")
    assert resp.status_code == 401, f"{reason} must be refused: {resp.text}"


async def test_a_token_signed_by_the_wrong_key_is_refused(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp
) -> None:
    """The signature check itself, with a token that is otherwise
    perfect."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await _configure(client, boss)
    state, nonce, binding = await _start(client)

    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    fake_idp.id_token = make_id_token(nonce=nonce, key=impostor)

    resp = await _callback(client, state=state, binding=binding, code="c")
    assert resp.status_code == 401


async def test_sso_config_is_refused_without_tenant_manage(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """`admin` is deliberately included: it is the most senior role that
    still lacks `tenant:manage`, and identity configuration is exactly the
    kind of thing that looks like it should fall under a general
    administrator."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    for role in ("learner", "admin"):
        token = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=role)
        headers = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/api/v1/tenant/sso", headers=headers)).status_code == 403
        assert (await client.delete("/api/v1/tenant/sso", headers=headers)).status_code == 403
        put = await client.put(
            "/api/v1/tenant/sso",
            json={
                "display_name": "x",
                "issuer": ISSUER,
                "client_id": CLIENT_ID,
                "client_secret": "s",
                "allowed_email_domains": ["allowed.example"],
                "group_role_map": {},
                "enabled": True,
            },
            headers=headers,
        )
        assert put.status_code == 403, f"{role} must not be able to configure SSO"


async def test_a_group_mapping_cannot_grant_authority_the_configurer_lacks(session) -> None:  # type: ignore[no-untyped-def]
    """An IdP group mapping is a role grant with extra steps, so
    `put_sso_config` puts every mapped role through the same
    `assert_can_grant` gate as manual assignment.

    This is tested at the service boundary rather than over HTTP for an
    honest reason: today only `super_admin` holds `tenant:manage`, and
    `super_admin` holds every permission, so no caller who can reach the
    endpoint can currently fail the check. The guard is there for the
    custom roles the permission table is built to allow — a role with
    `tenant:manage` and nothing else must not be able to mint
    `super_admin`s through an IdP group.
    """
    # Read from the database rather than restating the seed: role
    # permissions have already been extended by later migrations once
    # (0028 gave finance `analytics:view`), and a hardcoded set here
    # would fail for a reason that has nothing to do with SSO.
    finance_only = frozenset(
        await people.permissions_of_role(session, "finance") | {"tenant:manage"}
    )
    with pytest.raises(Forbidden):
        await people.assert_can_grant(
            session, role_code="super_admin", actor_permissions=finance_only
        )
    # The same caller mapping a group to a role it does hold is fine.
    await people.assert_can_grant(session, role_code="finance", actor_permissions=finance_only)


async def test_the_redirect_uri_is_derived_and_not_taken_from_the_caller(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp
) -> None:
    """`/auth/sso/start` is anonymous. If it accepted a `redirect_uri`,
    a stranger could name one — and against an identity provider with a
    loose or wildcard redirect registration, the authorisation code
    would be delivered to a host of their choosing."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await _configure(client, boss)

    resp = await client.post("/api/v1/auth/sso/start?redirect_uri=https://evil.example.com/collect")
    assert resp.status_code == 200, resp.text
    params = parse_qs(urlparse(resp.json()["authorization_url"]).query)
    assert params["redirect_uri"] == [EXPECTED_REDIRECT]
    assert "evil.example.com" not in resp.json()["authorization_url"]


@pytest.mark.parametrize("binding", [None, "", "a-binding-from-another-browser"])
async def test_a_callback_without_this_browsers_binding_is_refused(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp, binding: str | None
) -> None:
    """Login CSRF. `state` proves the callback belongs to a flow this
    server started; only the binding proves it belongs to *this*
    browser's flow. Without it an attacker starts a login, keeps the
    code and state, and links the victim at our own callback — the
    victim ends up silently signed into the attacker's account."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await _configure(client, boss)
    state, nonce, _ = await _start(client)
    fake_idp.id_token = make_id_token(nonce=nonce)

    resp = await _callback(client, state=state, binding=binding)
    assert resp.status_code == 401, resp.text


async def test_a_wrong_binding_burns_the_state(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto, fake_idp
) -> None:
    """A mismatch means the flow is already confused or under attack.
    Leaving the state redeemable would let an attacker keep retrying
    against a victim who has one live record."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    boss = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    await _configure(client, boss)
    state, nonce, binding = await _start(client)
    fake_idp.id_token = make_id_token(nonce=nonce)

    assert (await _callback(client, state=state, binding="wrong")).status_code == 401
    # Correct binding, same state — the record is gone.
    assert (await _callback(client, state=state, binding=binding)).status_code == 401


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("https://169.254.169.254/latest/meta-data/", "the cloud instance metadata service"),
        ("https://127.0.0.1/.well-known/openid-configuration", "loopback"),
        ("https://10.1.2.3/", "RFC1918 private space"),
        ("https://192.168.0.5/", "RFC1918 private space"),
        ("http://8.8.8.8/", "plain HTTP — an id_token is a credential"),
        ("ftp://8.8.8.8/", "a scheme that is not http(s)"),
        ("https:///no-host", "a URL naming no host"),
    ],
)
def test_the_egress_guard_refuses_what_no_identity_provider_should_be(url: str, why: str) -> None:
    """Post-authentication SSRF: the issuer is set by a tenant admin, so
    this is privileged — but it is still this server making a request to
    an address somebody else chose, and `PUT /tenant/sso` contacts the
    issuer before saving, which makes it a probe primitive.

    Literal addresses throughout: the guard resolves hostnames, and a
    test that needs a resolver is a test that fails on a train."""
    with pytest.raises(oidc.SsoError):
        oidc.assert_reachable_publicly(url)


def test_the_egress_guard_allows_a_public_https_host() -> None:
    oidc.assert_reachable_publicly("https://8.8.8.8/.well-known/openid-configuration")


def test_the_egress_guard_relaxes_only_when_the_caller_says_so() -> None:
    """A developer running a mock IdP on localhost needs both halves
    relaxed — scheme and address — and only outside production."""
    oidc.assert_reachable_publicly("http://127.0.0.1:9999/", allow_local=True)
