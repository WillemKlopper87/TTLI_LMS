"""Password hashing and token issuing.

Argon2id for passwords. SHA-256 for tokens, which are already high-entropy and
only ever compared — running Argon2 over a 32-byte random token buys nothing and
costs 250ms per request.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
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


def issue_access_token(
    *,
    secret: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    permissions: list[str],
    minutes: int,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "perms": permissions,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on anything wrong with the token."""
    decoded: dict[str, Any] = jwt.decode(token, secret, algorithms=[ALGORITHM])
    return decoded


__all__ = [
    "ALGORITHM",
    "decode_access_token",
    "hash_password",
    "hash_token",
    "issue_access_token",
    "needs_rehash",
    "new_token",
    "verify_password",
]
