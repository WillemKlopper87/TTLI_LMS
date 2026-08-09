"""Virus scanning via ClamAV's `clamd` daemon (04 §3, REQ-BYPASS-08:
"virus scanning before the file is readable by anyone").

Speaks clamd's INSTREAM protocol directly over a raw asyncio TCP
connection — four bytes of big-endian chunk length, then the chunk,
repeated, terminated by a zero-length chunk — rather than adding a
dependency for a protocol this small and this security-sensitive.

`routers/orders.py`'s payment-proof upload is the only caller today. It
fails closed: `ScanUnavailable` (clamd unreachable, or a genuinely
unexpected response) is treated the same as an infected file — refused,
never silently accepted unscanned.
"""

from __future__ import annotations

import asyncio
import struct

from src.core.config import Settings

# clamd's own default StreamMaxLength is 25 MiB; chunking well under that
# keeps this correct regardless of how a deployment's clamd.conf is tuned.
_CHUNK_SIZE = 2 * 1024 * 1024
_CONNECT_TIMEOUT_SECONDS = 5
_SCAN_TIMEOUT_SECONDS = 30


class ScanResult:
    def __init__(self, *, clean: bool, signature: str | None) -> None:
        self.clean = clean
        self.signature = signature


class ScanUnavailable(Exception):
    """clamd could not be reached, or replied with something this client
    doesn't understand. Callers must refuse the upload, not let it
    through unscanned."""


async def scan(data: bytes, *, settings: Settings) -> ScanResult:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.clamav_host, settings.clamav_port),
            timeout=_CONNECT_TIMEOUT_SECONDS,
        )
    except (OSError, TimeoutError) as exc:
        raise ScanUnavailable(f"Could not reach the virus scanner: {exc}") from exc

    try:
        writer.write(b"zINSTREAM\0")
        for offset in range(0, len(data), _CHUNK_SIZE):
            chunk = data[offset : offset + _CHUNK_SIZE]
            writer.write(struct.pack("!L", len(chunk)) + chunk)
        writer.write(struct.pack("!L", 0))
        await asyncio.wait_for(writer.drain(), timeout=_SCAN_TIMEOUT_SECONDS)

        raw = await asyncio.wait_for(reader.read(4096), timeout=_SCAN_TIMEOUT_SECONDS)
    except (OSError, TimeoutError) as exc:
        raise ScanUnavailable(f"The virus scanner did not respond: {exc}") from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    # clamd replies "stream: OK\0" or "stream: <signature> FOUND\0".
    response = raw.decode("utf-8", errors="replace").rstrip("\0").strip()
    if response.endswith("OK"):
        return ScanResult(clean=True, signature=None)
    if "FOUND" in response:
        signature = response.removeprefix("stream:").removesuffix("FOUND").strip()
        return ScanResult(clean=False, signature=signature)
    raise ScanUnavailable(f"Unexpected response from the virus scanner: {response!r}")


__all__ = ["ScanResult", "ScanUnavailable", "scan"]
