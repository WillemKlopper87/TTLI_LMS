"""Field-level encryption and blind indexing.

The customer's requirement was that captured information be "salted and hashed".
Hashing is one-way, and most of this data has to be read back — an email address
that has been hashed cannot receive an invoice. So the split is:

  hash    what is only ever verified   (passwords, tokens)   -> security.py
  encrypt what has to be read back     (email, name, phone)  -> here

with a keyed blind index alongside the ciphertext so encrypted values remain
searchable. See docs/04_SECURITY_AND_COMPLIANCE.md section 4.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


class CryptoBox:
    """AES-GCM field encryption plus an HMAC blind index.

    The two keys must differ. If the index key is derived from the data key,
    a single compromise breaks both properties at once.
    """

    def __init__(self, encryption_key: bytes, index_key: bytes) -> None:
        if len(encryption_key) != 32:
            raise ValueError("encryption key must be 32 bytes")
        if len(index_key) < 32:
            raise ValueError("index key must be at least 32 bytes")
        if encryption_key == index_key:
            raise ValueError("encryption and index keys must differ")
        self._aead = AESGCM(encryption_key)
        self._index_key = index_key

    def encrypt(self, plaintext: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext.encode("utf-8"), None)

    def decrypt(self, blob: bytes) -> str:
        nonce, ciphertext = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        return self._aead.decrypt(nonce, ciphertext, None).decode("utf-8")

    def blind_index(self, value: str) -> bytes:
        """Deterministic, keyed lookup token.

        Deterministic by necessity — login has to find the row. That leaks
        equality: an attacker holding a dump can tell two rows share an address,
        though not what it is. Accepted, and recorded in the security doc.
        """
        normalised = value.strip().lower().encode("utf-8")
        return hmac.new(self._index_key, normalised, hashlib.sha256).digest()


__all__ = ["NONCE_BYTES", "CryptoBox"]
