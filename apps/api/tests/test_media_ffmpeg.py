"""Pure-function coverage for the ladder-args builder and binary
resolution (06 §3.2) — no ffmpeg process involved, so these run without
any service dependency. The real-transcode path is covered separately in
tests/test_media.py against actual ffmpeg, the same "don't mock the thing
a wire-protocol bug would hide behind" reasoning as test_antivirus.py.
"""

from __future__ import annotations

import pytest
from src.services.media.ffmpeg import (
    DEFAULT_RUNGS,
    LADDER,
    FfmpegError,
    ProbeResult,
    build_ladder_args,
    resolve_binary,
)


def _probe(*, has_audio: bool = True, fps: float = 25.0, duration: float = 10.0) -> ProbeResult:
    return ProbeResult(duration_seconds=duration, has_audio=has_audio, fps=fps)


def test_build_ladder_args_rejects_unknown_rung() -> None:
    with pytest.raises(FfmpegError, match="Unknown ladder rung"):
        build_ladder_args(("4k",), _probe(), x264_preset="veryfast")


def test_build_ladder_args_maps_one_stream_per_rung() -> None:
    args = build_ladder_args(("480p", "720p"), _probe(), x264_preset="veryfast")
    assert args.count("-c:v:0") == 1
    assert args.count("-c:v:1") == 1
    assert "libx264" in args


def test_build_ladder_args_omits_audio_mapping_when_source_has_none() -> None:
    args = build_ladder_args(("480p",), _probe(has_audio=False), x264_preset="veryfast")
    assert "-c:a:0" not in args


def test_build_ladder_args_includes_audio_mapping_when_source_has_it() -> None:
    args = build_ladder_args(("480p",), _probe(has_audio=True), x264_preset="veryfast")
    assert "-c:a:0" in args
    assert "aac" in args


def test_build_ladder_args_gop_derives_from_fps_and_segment_length() -> None:
    # SEGMENT_SECONDS is 6; 30fps * 6s = 180-frame GOP.
    args = build_ladder_args(("480p",), _probe(fps=30.0), x264_preset="veryfast")
    g_index = args.index("-g")
    assert args[g_index + 1] == "180"


def test_build_ladder_args_is_vod_only_no_live_sliding_window() -> None:
    args = build_ladder_args(("480p",), _probe(), x264_preset="veryfast")
    assert "-hls_playlist_type" in args
    assert args[args.index("-hls_playlist_type") + 1] == "vod"
    assert "-hls_list_size" in args
    assert args[args.index("-hls_list_size") + 1] == "0"


def test_default_rungs_are_all_in_the_ladder() -> None:
    assert all(r in LADDER for r in DEFAULT_RUNGS)


def test_resolve_binary_prefers_a_valid_override() -> None:
    import sys

    # sys.executable is a real file guaranteed to exist on any machine
    # running this test — stands in for a real ffmpeg path without
    # depending on ffmpeg actually being installed.
    resolved = resolve_binary("ffmpeg", override=sys.executable)
    assert resolved == sys.executable


def test_resolve_binary_ignores_a_nonexistent_override() -> None:
    resolved = resolve_binary("ffmpeg", override="/definitely/not/a/real/path/ffmpeg")
    assert resolved != "/definitely/not/a/real/path/ffmpeg"
