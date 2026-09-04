from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class VideoAssetResponse(BaseModel):
    id: str
    state: str
    duration_seconds: int | None
    has_captions: bool = False
    delivery_mode: str = "hls"
    source_filename: str | None = None
    source_size_bytes: int | None = None
    # {rung: bytes} for every known rung, not just the ones eventually
    # chosen — the decision panel needs a size preview for every checkbox
    # as the admin toggles it, not just the pre-selected default.
    estimated_sizes: dict[str, int] = {}
    default_rungs: list[str] = []
    allow_bypass: bool = True
    requested_rungs: list[str] = []


class VideoAssetsPageResponse(BaseModel):
    items: list[VideoAssetResponse]


class AudioAssetResponse(BaseModel):
    """No rungs/renditions/delivery_mode (0041) — an audio asset is
    always stored-and-served exactly as uploaded, never transcoded."""

    id: str
    state: str
    duration_seconds: int | None
    source_filename: str | None = None
    source_size_bytes: int | None = None


class AudioAssetsPageResponse(BaseModel):
    items: list[AudioAssetResponse]


class VideoFinalizeRequest(BaseModel):
    mode: Literal["as_is", "transcode"]
    rungs: list[str] = []


class WatermarkPayload(BaseModel):
    text: str
    opacity: float


class AudioPlaybackResponse(BaseModel):
    """No watermark/delivery_mode (0041) — an audio asset has exactly one
    delivery shape (store-and-serve), unlike video's hls/progressive
    split, and nothing burns a watermark into an audio stream the way
    the transcode pipeline does for video."""

    audio_url: str
    expires_at: datetime


class PlaybackResponse(BaseModel):
    playlist_url: str
    captions_url: str | None = None
    expires_at: datetime
    watermark: WatermarkPayload
    delivery_mode: Literal["hls", "progressive"] = "hls"


__all__ = [
    "AudioAssetResponse",
    "AudioAssetsPageResponse",
    "AudioPlaybackResponse",
    "PlaybackResponse",
    "VideoAssetResponse",
    "VideoAssetsPageResponse",
    "VideoFinalizeRequest",
    "WatermarkPayload",
]
