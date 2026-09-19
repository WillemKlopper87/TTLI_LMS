"""M3: a shared, bounded read for every upload endpoint.

Every upload router in this app used to call a bare `await file.read()`
before any size check ran — video, audio, captions, PO/payment-proof
documents, assignment submissions. A caller with no more authority than
an enrolled learner (assignment submission) or a customer with an order
(payment proof) could POST a multi-GB body; the whole thing is read into
process memory before `bypass_max_size_bytes` or any other limit is ever
consulted, and a handful of concurrent requests OOM the API process. A
production edge proxy may also cap body size, but the app itself must
not depend on that.
"""

from __future__ import annotations

from fastapi import UploadFile

from src.core.errors import PayloadTooLarge

_DEFAULT_CHUNK_SIZE = 1024 * 1024


async def read_upload_within_limit(
    file: UploadFile, *, max_bytes: int, chunk_size: int = _DEFAULT_CHUNK_SIZE
) -> bytes:
    """Read `file` in bounded chunks, refusing the moment the stream
    exceeds `max_bytes` — the running total never buffers more than one
    chunk past the limit, unlike reading the whole body first and
    checking `len(data)` afterwards."""
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLarge(f"That file exceeds the {max_bytes:,}-byte limit.")
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ["read_upload_within_limit"]
