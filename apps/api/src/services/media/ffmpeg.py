"""Binary resolution, source probing, and the ladder-args builder — ported
from Streaming_Server's `ffmpeg-controller.js::resolveFFmpegPath` and
`transcoding-engine.js::probeSource`/`buildLadderArgs` (06 §3.2). Pure
functions apart from the two that spawn a subprocess, so the argument-
building logic is testable without ever invoking ffmpeg.

Only the VOD path is ported. Live mode (`transcoding-engine.js`'s sliding
HLS window) is not — 01 §5.8 already decided this platform never streams
live broadcast content, so porting a mode nothing here will ever use would
be unexercised code carrying its own bug surface for no reason.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

# Segment duration drives GOP length — every rendition places an IDR at
# exactly this cadence so segments are switchable across the ladder.
SEGMENT_SECONDS = 6

# ABR ladder (06 §3.2's table) — height/kbps/profile/level per rung.
# maxrate/bufsize give each rung a declared VBV so output is
# rate-constrained rather than an unconstrained VBR overshoot.
LADDER: dict[str, dict[str, int | str]] = {
    # Opt-in only (0040) — genuinely slow connections. Never in
    # DEFAULT_RUNGS, so a tenant/course that hasn't touched video
    # settings sees no change. Same maxrate/bufsize ratio as 480p
    # (1.10x / 2.00x video_kbps); baseline profile for maximum
    # compatibility on the weakest devices likely to pick this rung.
    "360p": {
        "width": 640,
        "height": 360,
        "video_kbps": 600,
        "maxrate_kbps": 660,
        "bufsize_kbps": 1200,
        "audio_kbps": 64,
        "profile": "baseline",
        "level": "3.0",
    },
    "480p": {
        "width": 854,
        "height": 480,
        "video_kbps": 1200,
        "maxrate_kbps": 1320,
        "bufsize_kbps": 2400,
        "audio_kbps": 96,
        "profile": "main",
        "level": "3.1",
    },
    "720p": {
        "width": 1280,
        "height": 720,
        "video_kbps": 2800,
        "maxrate_kbps": 3080,
        "bufsize_kbps": 5600,
        "audio_kbps": 128,
        "profile": "main",
        "level": "3.2",
    },
    "1080p": {
        "width": 1920,
        "height": 1080,
        "video_kbps": 5000,
        "maxrate_kbps": 5500,
        "bufsize_kbps": 10000,
        "audio_kbps": 128,
        "profile": "high",
        "level": "4.0",
    },
}
DEFAULT_RUNGS = ("480p", "720p", "1080p")


class FfmpegError(Exception):
    pass


def resolve_binary(name: str, *, override: str = "") -> str:
    """Same search order as `resolveFFmpegPath` (06 §3.2's ported
    behaviour): an explicit override, common Unix install locations, then
    whatever the OS resolves from PATH. No `ffmpeg-static` fallback —
    that was a Node-packaging concern; Python has no equivalent bundled
    binary, so a missing ffmpeg surfaces as a real spawn error instead."""
    if override and Path(override).exists():
        return override
    for candidate in (f"/usr/bin/{name}", f"/usr/local/bin/{name}", f"/opt/homebrew/bin/{name}"):
        if Path(candidate).exists():
            return candidate
    return shutil.which(name) or name


@dataclass(frozen=True, slots=True)
class ProbeResult:
    duration_seconds: float
    has_audio: bool
    fps: float


async def probe_source(input_file: Path, *, ffprobe_path: str) -> ProbeResult:
    """Duration gives a real completion percentage; audio presence decides
    whether the ladder maps an audio stream at all — mapping one that
    doesn't exist aborts ffmpeg outright."""
    proc = await asyncio.create_subprocess_exec(
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,avg_frame_rate",
        "-of",
        "json",
        str(input_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FfmpegError(f"ffprobe failed: {stderr.decode(errors='replace').strip()}")

    probe = json.loads(stdout)
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)

    fps = 25.0
    frame_rate = video.get("avg_frame_rate") if video else None
    if frame_rate and frame_rate != "0/0":
        num_str, _, den_str = frame_rate.partition("/")
        num, den = int(num_str), int(den_str or "1")
        if den > 0 and num > 0:
            fps = num / den

    return ProbeResult(
        duration_seconds=float(probe.get("format", {}).get("duration") or 0),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        fps=fps,
    )


def build_ladder_args(rungs: tuple[str, ...], probe: ProbeResult, *, x264_preset: str) -> list[str]:
    """One decode, N encodes via `split` in the filter graph (06 §3.2) —
    three separate ffmpeg processes would let each encoder place IDR
    frames independently, and segment boundaries would then not align,
    which is the specific failure this single-process approach avoids.
    `-i` is intentionally not included here — the caller prepends it so
    this function stays a pure arg-list builder, easy to unit test without
    a real file on disk.
    """
    unknown = [r for r in rungs if r not in LADDER]
    if unknown:
        raise FfmpegError(f"Unknown ladder rung(s): {', '.join(unknown)}")

    gop = max(1, round(probe.fps * SEGMENT_SECONDS))
    split_labels = "".join(f"[v{i}]" for i in range(len(rungs)))
    scale_chains = ";".join(
        f"[v{i}]scale=w={LADDER[r]['width']}:h={LADDER[r]['height']}:"
        f"force_original_aspect_ratio=decrease,"
        f"pad={LADDER[r]['width']}:{LADDER[r]['height']}:-1:-1,setsar=1[v{i}out]"
        for i, r in enumerate(rungs)
    )

    args = [
        "-filter_complex",
        f"[0:v]split={len(rungs)}{split_labels};{scale_chains}",
    ]
    for i, r in enumerate(rungs):
        cfg = LADDER[r]
        args += [
            "-map",
            f"[v{i}out]",
            f"-c:v:{i}",
            "libx264",
            f"-b:v:{i}",
            f"{cfg['video_kbps']}k",
            f"-maxrate:v:{i}",
            f"{cfg['maxrate_kbps']}k",
            f"-bufsize:v:{i}",
            f"{cfg['bufsize_kbps']}k",
            f"-profile:v:{i}",
            str(cfg["profile"]),
            f"-level:v:{i}",
            str(cfg["level"]),
        ]
    if probe.has_audio:
        for i, r in enumerate(rungs):
            cfg = LADDER[r]
            args += [
                "-map",
                "a:0",
                f"-c:a:{i}",
                "aac",
                f"-b:a:{i}",
                f"{cfg['audio_kbps']}k",
                f"-ac:a:{i}",
                "2",
            ]

    args += [
        # A single preset for the whole ladder — mixing presets per rung
        # changes rate-control behaviour for no benefit.
        "-preset",
        x264_preset,
        # Closed, fixed-length GOPs with IDRs pinned to segment
        # boundaries. Without this the renditions are not switchable.
        "-g",
        str(gop),
        "-keyint_min",
        str(gop),
        "-sc_threshold",
        "0",
        "-force_key_frames",
        f"expr:gte(t,n_forced*{SEGMENT_SECONDS})",
        "-progress",
        "pipe:1",
        "-f",
        "hls",
        "-hls_time",
        str(SEGMENT_SECONDS),
        # VOD only (see module docstring) — complete asset retained,
        # playlist closed with ENDLIST. The live sliding-window mode this
        # was ported from is deliberately not carried over.
        "-hls_list_size",
        "0",
        "-hls_playlist_type",
        "vod",
        "-hls_flags",
        "independent_segments+program_date_time",
        # fMP4 segments (CMAF), not legacy MPEG-TS.
        "-hls_segment_type",
        "fmp4",
        # Bare, relative output names — ffmpeg runs with cwd set to the
        # job's output directory (06 §3.2's flat-layout note: a nested
        # layout leaves EXT-X-MAP pointing outside the variant folder).
        "-hls_fmp4_init_filename",
        "init.mp4",
        "-master_pl_name",
        "master.m3u8",
        "-hls_segment_filename",
        "seg_%v_%05d.m4s",
        "-var_stream_map",
        " ".join((f"v:{i},a:{i}" if probe.has_audio else f"v:{i}") for i in range(len(rungs))),
        "index_%v.m3u8",
    ]
    return args


__all__ = [
    "DEFAULT_RUNGS",
    "LADDER",
    "SEGMENT_SECONDS",
    "FfmpegError",
    "ProbeResult",
    "build_ladder_args",
    "probe_source",
    "resolve_binary",
]
