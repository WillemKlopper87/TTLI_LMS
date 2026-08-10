from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VideoAssetResponse(BaseModel):
    id: str
    state: str
    duration_seconds: int | None
    has_captions: bool = False


class WatermarkPayload(BaseModel):
    text: str
    opacity: float


class PlaybackResponse(BaseModel):
    playlist_url: str
    captions_url: str | None = None
    expires_at: datetime
    watermark: WatermarkPayload


__all__ = ["PlaybackResponse", "VideoAssetResponse", "WatermarkPayload"]
