from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import jwt
import pytest
from src.core.ids import uuid7
from src.core.security import (
    decode_access_token,
    hash_password,
    hash_password_async,
    hash_token,
    issue_access_token,
    new_token,
    verify_password,
    verify_password_async,
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


# --- H-14: Argon2 must not be run on the event loop --------------------


@pytest.mark.unit
async def test_the_async_wrappers_agree_with_the_blocking_ones() -> None:
    stored = await hash_password_async("correct horse battery staple")
    assert stored.startswith("$argon2id$")
    assert await verify_password_async("correct horse battery staple", stored)
    assert not await verify_password_async("wrong", stored)
    # The two families are interchangeable, so a hash written by the
    # migration or the seed script verifies through the async path.
    assert await verify_password_async("right", hash_password("right"))
    assert verify_password("right", await hash_password_async("right"))


@pytest.mark.unit
async def test_verifying_a_password_leaves_the_event_loop_running() -> None:
    """fable5.1 review H-14. One Argon2 verification costs ~250ms by
    design; spent on the loop it is 250ms in which this process serves
    nobody — not a heartbeat, not a payment webhook, not another login.
    Four logins a second from four addresses, well inside the
    10-per-minute per-IP limit, was enough to hold the loop down.

    Asserted by what a blocked loop cannot do: keep a ticker running. The
    blocking `verify_password` fails this; the wrapper passes it.
    """
    stored = hash_password("correct horse battery staple")
    ticks = 0
    stop = False

    async def ticker() -> None:
        nonlocal ticks
        while not stop:
            ticks += 1
            await asyncio.sleep(0.001)

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.01)
    before = ticks

    assert await verify_password_async("correct horse battery staple", stored)

    after = ticks
    stop = True
    await task

    # Deliberately a low bar rather than a count proportional to the
    # hash's duration: this asserts "the loop kept running", not a timing
    # figure that would flake on a loaded CI box.
    assert after > before, "the event loop made no progress during the verification"


@pytest.mark.unit
def test_the_login_path_never_calls_the_blocking_primitives() -> None:
    """The wrappers only help if the hot path actually uses them, and
    nothing in the type system stops the next edit from reaching for the
    blocking name — it is still exported, legitimately, for the migration
    and the seed script.

    `_DUMMY_HASH` is the one blocking call left in that module: it runs
    once at import, before any request exists.
    """
    source = (Path(__file__).resolve().parents[1] / "src" / "services" / "identity.py").read_text(
        encoding="utf-8"
    )
    without_async = source.replace("hash_password_async(", "").replace("verify_password_async(", "")
    assert "verify_password(" not in without_async
    assert without_async.count("hash_password(") == 1, (
        "only _DUMMY_HASH may hash synchronously in the identity service"
    )
