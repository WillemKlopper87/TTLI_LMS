from __future__ import annotations

import time
import uuid

import jwt
import pytest
from src.core.ids import uuid7
from src.core.security import (
    decode_access_token,
    hash_password,
    hash_token,
    issue_access_token,
    new_token,
    verify_password,
)

SECRET = "test-secret-key-at-least-32-characters-long"


def test_password_roundtrip() -> None:
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)


def test_wrong_password_rejected() -> None:
    assert not verify_password("wrong", hash_password("right"))


def test_hash_is_salted() -> None:
    """Same password, different hashes — a rainbow table buys nothing."""
    assert hash_password("same") != hash_password("same")


def test_argon2id_is_used() -> None:
    assert hash_password("x").startswith("$argon2id$")


def test_malformed_hash_does_not_raise() -> None:
    """A corrupted column must fail the login, not 500 the endpoint."""
    assert not verify_password("anything", "not-a-hash")


def test_token_hash_is_stable_and_one_way() -> None:
    raw = new_token()
    assert hash_token(raw) == hash_token(raw)
    assert raw.encode() not in hash_token(raw)


def test_access_token_roundtrip() -> None:
    user_id, tenant_id = uuid7(), uuid7()
    token = issue_access_token(
        secret=SECRET,
        user_id=user_id,
        tenant_id=tenant_id,
        permissions=["course:view"],
        minutes=15,
    )
    claims = decode_access_token(token, secret=SECRET)
    assert claims["sub"] == str(user_id)
    assert claims["tid"] == str(tenant_id)
    assert claims["perms"] == ["course:view"]


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = issue_access_token(
        secret=SECRET, user_id=uuid7(), tenant_id=uuid7(), permissions=[], minutes=15
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token, secret="a-different-secret-of-sufficient-length")


def test_expired_token_is_rejected() -> None:
    token = issue_access_token(
        secret=SECRET, user_id=uuid7(), tenant_id=uuid7(), permissions=[], minutes=-1
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, secret=SECRET)


def test_uuid7_is_version_7_and_rfc4122() -> None:
    value = uuid7()
    assert value.version == 7
    assert (value.bytes[8] & 0xC0) == 0x80


def test_uuid7_is_time_ordered() -> None:
    """Time-ordered, so it indexes like a sequence rather than scattering pages."""
    first = uuid7()
    time.sleep(0.005)
    second = uuid7()
    assert first.bytes[:6] <= second.bytes[:6]
    assert uuid.UUID(str(first)) == first


def test_uuid7_is_unique_within_a_millisecond() -> None:
    values = {uuid7() for _ in range(2000)}
    assert len(values) == 2000
