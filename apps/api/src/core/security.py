"""Password hashing and token issuing.

Argon2id for passwords. SHA-256 for tokens, which are already high-entropy and
only ever compared — running Argon2 over a 32-byte random token buys nothing and
costs 250ms per request.

**Async callers want `hash_password_async` / `verify_password_async`.** The
250ms is deliberate — it is what makes the hash expensive to attack — but spent
on the event loop it is 250ms during which this process serves nobody:
not a heartbeat, not a payment webhook, not another login. Roughly four logins
a second from four different addresses, comfortably inside the 10-per-minute
per-IP limit, is enough to hold the loop down continuously (fable5.1 review
H-14). The blocking versions below stay for the callers that are genuinely
synchronous — migration `0002`, `scripts/seed_e2e_accounts.py`, and the unit
tests — and for `_DUMMY_HASH`, which is computed once at import.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Tuned so one verification costs roughly 250ms on the target hardware. Re-tune
# against production, not against a laptop.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


async def hash_password_async(password: str) -> str:
    """`hash_password` off the event loop. See the module docstring."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, stored_hash: str) -> bool:
    """`verify_password` off the event loop. See the module docstring.

    The thread hop does not weaken the constant-time-ish property the login
    path relies on: the dummy-hash verification callers do for a missing
    user goes through this same wrapper, so both branches pay the same
    hop as well as the same Argon2 cost.
    """
    return await asyncio.to_thread(verify_password, password, stored_hash)


def needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash predates the current cost parameters."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except (InvalidHashError, ValueError):
        return True


def new_token() -> str:
    """A raw bearer token. Shown once, never stored in this form."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


def new_recovery_code() -> str:
    """A human-typeable MFA recovery code. Shown once, stored only as a hash."""
    raw = secrets.token_hex(5).upper()
    return f"{raw[:5]}-{raw[5:]}"


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(*, secret: str, account_email: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_email, issuer_name=issuer)


def verify_totp(*, secret: str, code: str) -> bool:
    """±1 step (30s) window, per 04_SECURITY_AND_COMPLIANCE.md §1.3."""
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False


def issue_access_token(
    *,
    secret: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    permissions: list[str],
    minutes: int,
    perm_generation: int = 0,
    guest_expires_at: datetime | None = None,
) -> str:
    """`perm_generation` (M6) stamps the permission-generation the caller
    read `permissions` at — 0 for any caller not tracking one, which
    also matches `tokens.permission_generation`'s own default for a user
    nothing has ever bumped, so an old token minted before this claim
    existed and a fresh one for an untouched user compare equal against
    a never-bumped counter. `core/deps.get_principal` refuses a token
    whose stamped generation is behind the current one.

    `guest_expires_at` (L9), set only when the caller is a guest, stamps
    the `gexp` claim `get_principal` compares to wall-clock `now()` on
    every request — the same shape this function's own `exp` claim
    already uses, and deliberately not a live database re-read: unlike
    `/auth/refresh` (which re-reads `guest_expires_at` fresh as part of
    a DB round-trip it needs anyway — `services/tokens.py::rotate`),
    `get_principal` runs on every authenticated request in the app, and
    a claim comparison is the low-risk way to close "an already-issued
    access token outlives the guest window it was minted inside," at
    the cost of not reflecting a guest's `guest_expires_at` changing
    again after this token was minted — the same residual a JWT's own
    `exp` always has by nature.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "perms": permissions,
        "pgen": perm_generation,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    if guest_expires_at is not None:
        payload["gexp"] = int(guest_expires_at.timestamp())
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on anything wrong with the token.

    A purpose token (MFA challenge, MFA enrolment) is signed with the same
    secret and carries the same `sub`/`tid` claims an access token does, so
    signature + expiry alone cannot tell them apart. Rejecting any token
    that carries `purpose` is what makes issue_purpose_token's "never
    accepted as an access token" guarantee actually true — without it, an
    attacker holding only a password could spend the MFA challenge token
    as a bearer for its whole lifetime instead of completing TOTP.
    """
    decoded: dict[str, Any] = jwt.decode(token, secret, algorithms=[ALGORITHM])
    if "purpose" in decoded:
        raise jwt.InvalidTokenError("not an access token")
    return decoded


def issue_purpose_token(*, secret: str, purpose: str, claims: dict[str, Any], minutes: int) -> str:
    """A short-lived JWT for a single intent — an MFA challenge or an MFA
    enrolment in progress — never accepted as an access token because its
    `purpose` does not match what decode_purpose_token requires.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "purpose": purpose,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        **claims,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_purpose_token(token: str, *, secret: str, purpose: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError — including on a purpose mismatch, deliberately
    the same exception type as an expired or malformed token."""
    decoded: dict[str, Any] = jwt.decode(token, secret, algorithms=[ALGORITHM])
    if decoded.get("purpose") != purpose:
        raise jwt.InvalidTokenError("wrong token purpose")
    return decoded


__all__ = [
    "ALGORITHM",
    "decode_access_token",
    "decode_purpose_token",
    "hash_password",
    "hash_password_async",
    "hash_token",
    "issue_access_token",
    "issue_purpose_token",
    "needs_rehash",
    "new_recovery_code",
    "new_token",
    "new_totp_secret",
    "totp_provisioning_uri",
    "verify_password",
    "verify_password_async",
    "verify_totp",
]
