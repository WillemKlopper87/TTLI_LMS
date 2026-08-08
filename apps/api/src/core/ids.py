"""UUID v7 generation.

Postgres only gained a native `uuidv7()` in 18; we are on 16, so identifiers are
generated in the application. v7 is time-ordered, so it indexes like a sequence
without publishing a row count the way `bigserial` does.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """A UUID version 7: 48-bit big-endian millisecond timestamp, then random."""
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70  # version 7
    b[8] = (b[8] & 0x3F) | 0x80  # RFC 4122 variant
    return uuid.UUID(bytes=bytes(b))


__all__ = ["uuid7"]
