from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VideoAssetResponse(BaseModel):
    id: str
    state: str
    duration_seconds: int | None


class WatermarkPayload(BaseModel):
    text: str
    opacity: float


class PlaybackResponse(BaseModel):
    playlist_url: str
    expires_at: datetime
    watermark: WatermarkPayload


__all__ = ["PlaybackResponse", "VideoAssetResponse", "WatermarkPayload"]
