from __future__ import annotations

import base64

import pytest
from src.core.crypto import CryptoBox


@pytest.fixture
def box() -> CryptoBox:
    return CryptoBox(b"K" * 32, b"I" * 32)


def test_encrypt_decrypt_roundtrip(box: CryptoBox) -> None:
    assert box.decrypt(box.encrypt("thandi.nkosi@meridian.co.za")) == "thandi.nkosi@meridian.co.za"


def test_ciphertext_differs_each_time(box: CryptoBox) -> None:
    """A fresh nonce per call, so equal plaintexts do not produce equal rows."""
    a, b = box.encrypt("same@example.com"), box.encrypt("same@example.com")
    assert a != b
    assert box.decrypt(a) == box.decrypt(b)


def test_blind_index_is_deterministic(box: CryptoBox) -> None:
    """Login has to find the row, so the index must be stable."""
    assert box.blind_index("user@example.com") == box.blind_index("user@example.com")


def test_blind_index_normalises_case_and_whitespace(box: CryptoBox) -> None:
    assert box.blind_index("  User@Example.COM ") == box.blind_index("user@example.com")


def test_blind_index_differs_by_value(box: CryptoBox) -> None:
    assert box.blind_index("a@example.com") != box.blind_index("b@example.com")


def test_blind_index_is_keyed() -> None:
    """A dump without the index key is not brute-forceable by hashing guesses."""
    one = CryptoBox(b"K" * 32, b"I" * 32)
    two = CryptoBox(b"K" * 32, b"J" * 32)
    assert one.blind_index("user@example.com") != two.blind_index("user@example.com")


def test_tampered_ciphertext_is_rejected(box: CryptoBox) -> None:
    """AES-GCM is authenticated: a flipped byte fails, it does not decrypt to junk."""
    blob = bytearray(box.encrypt("user@example.com"))
    blob[-1] ^= 0x01
    with pytest.raises(Exception):  # noqa: B017 - cryptography raises InvalidTag
        box.decrypt(bytes(blob))


def test_keys_must_differ() -> None:
    with pytest.raises(ValueError, match="must differ"):
        CryptoBox(b"K" * 32, b"K" * 32)


def test_encryption_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        CryptoBox(base64.b64decode(base64.b64encode(b"short")), b"I" * 32)
