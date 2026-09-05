"""Subprocess orchestration for the ladder transcode (06 §3.2, ported from
`transcoding-engine.js::initializeTranscoding`/`_consumeProgress`). Spawns
one ffmpeg process for the whole ladder — cwd set to the job's output
directory so every emitted filename in the HLS manifests stays relative
and resolvable, exactly the flat-layout requirement `ffmpeg.py` documents.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from src.services.media.ffmpeg import ProbeResult, build_ladder_args

# -progress emits roughly twice a second; a caller (the arq job) does not
# need every one of those as a database round-trip.
PROGRESS_THROTTLE_SECONDS = 5.0

_OUT_TIME_US_RE = re.compile(rb"out_time_us=(\d+)")


class TranscodeFailed(Exception):
    def __init__(self, message: str, *, returncode: int | None) -> None:
        super().__init__(message)
        self.returncode = returncode


async def run_transcode(
    input_file: Path,
    output_dir: Path,
    rungs: tuple[str, ...],
    probe: ProbeResult,
    *,
    ffmpeg_path: str,
    x264_preset: str = "veryfast",
    on_progress: Callable[[float, int], Awaitable[None]] | None = None,
) -> None:
    """Runs to completion or raises TranscodeFailed. `on_progress` is
    awaited with `(processed_seconds, progress_pct)`, throttled to at most
    once every `PROGRESS_THROTTLE_SECONDS` — matching the source engine's
    `PROGRESS_PERSIST_MS`, ported to Python's step in seconds.
    """
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
    args = [ffmpeg_path, "-hide_banner", "-loglevel", "warning", "-nostats", "-i", str(input_file)]
    args += build_ladder_args(rungs, probe, x264_preset=x264_preset)

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(output_dir),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    if proc.stdout is None or proc.stderr is None:  # pragma: no cover - always PIPE above
        raise TranscodeFailed("ffmpeg process has no stdout/stderr pipe.", returncode=None)

    stderr_tail: list[bytes] = []

    async def _drain_stdout(stdout: asyncio.StreamReader) -> None:
        last_persisted = 0.0
        async for line in stdout:
            match = _OUT_TIME_US_RE.search(line)
            if not match:
                continue
            processed_seconds = int(match.group(1)) / 1_000_000
            now = time.monotonic()
            if on_progress is not None and now - last_persisted >= PROGRESS_THROTTLE_SECONDS:
                last_persisted = now
                pct = 0
                if probe.duration_seconds > 0:
                    pct = min(99, round((processed_seconds / probe.duration_seconds) * 100))
                await on_progress(processed_seconds, pct)

    async def _drain_stderr(stderr: asyncio.StreamReader) -> None:
        async for line in stderr:
            stderr_tail.append(line)
            if len(stderr_tail) > 50:
                stderr_tail.pop(0)

    try:
        await asyncio.gather(_drain_stdout(proc.stdout), _drain_stderr(proc.stderr), proc.wait())
    except asyncio.CancelledError:
        # The worker's job timeout cancels this coroutine; ffmpeg is a
        # separate OS process and would otherwise keep transcoding an
        # asset nobody is waiting for any more, holding a CPU and the
        # temporary directory the caller is about to delete out from
        # under it (fable5.1 review H-5). Kill, reap, and let the
        # cancellation continue on its way — never swallowed.
        if proc.returncode is None:
            proc.kill()
            await asyncio.shield(proc.wait())
        raise

    if proc.returncode != 0:
        tail = b"".join(stderr_tail).decode(errors="replace").strip()
        raise TranscodeFailed(
            f"ffmpeg exited with code {proc.returncode}: {tail[-2000:]}",
            returncode=proc.returncode,
        )


__all__ = ["PROGRESS_THROTTLE_SECONDS", "TranscodeFailed", "run_transcode"]
