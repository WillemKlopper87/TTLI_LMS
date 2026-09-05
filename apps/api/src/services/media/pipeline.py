"""The end-to-end job: fetch the source from storage, transcode locally,
upload the HLS output, update `video_assets`/`transcode_jobs`. Called by
the arq worker (`src/workers/main.py::transcode_video_job`) — kept as a
plain function, not an arq task itself, so it stays testable without a
running worker process.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.ids import uuid7
from src.core.logging import get_logger
from src.models.media import TranscodeJob, VideoAsset
from src.services.media import ffmpeg as ffmpeg_service
from src.services.media.transcoder import TranscodeFailed, run_transcode
from src.services.storage import Container, StorageService

log = get_logger(__name__)

_CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".mp4": "video/mp4",
    ".m4s": "video/iso.segment",
}


def _content_type_for(filename: str) -> str:
    return _CONTENT_TYPES.get(Path(filename).suffix, "application/octet-stream")


# `video_assets.state` has always used "failed"; `transcode_jobs.state` was
# written as "error" while `services/operations.py` queried it for
# "failed", so the operations screen's "needs attention" list has never
# shown a failed transcode. One spelling, and the query accepts the old
# one so rows already written stay visible.
FAILED_STATE = "failed"


def _object_prefix(video_asset_id: uuid.UUID) -> str:
    return f"video-assets/{video_asset_id}"


async def transcode_video_asset(
    session: AsyncSession,
    storage: StorageService,
    settings: Settings,
    *,
    video_asset_id: uuid.UUID,
) -> None:
    asset = await session.get(VideoAsset, video_asset_id)
    if asset is None:
        raise ValueError(f"No such video asset: {video_asset_id}")

    job = TranscodeJob(id=uuid7(), state="transcoding", started_at=datetime.now(UTC))
    session.add(job)
    await session.flush()
    asset.transcode_job_id = job.id
    asset.state = "transcoding"
    await session.commit()

    ffmpeg_path = ffmpeg_service.resolve_binary("ffmpeg", override=settings.ffmpeg_path)
    ffprobe_path = ffmpeg_service.resolve_binary("ffprobe", override=settings.ffprobe_path)

    with tempfile.TemporaryDirectory(prefix="ttli-transcode-") as tmp:
        source_path = Path(tmp) / "source"
        output_dir = Path(tmp) / "output"

        source_bytes = await storage.get_object(Container.PRIVATE_CONTENT, asset.source_object_key)
        source_path.write_bytes(source_bytes)

        async def on_progress(processed_seconds: float, pct: int) -> None:
            job.processed_seconds = Decimal(str(round(processed_seconds, 2)))
            job.progress_pct = pct
            await session.commit()

        try:
            probe = await ffmpeg_service.probe_source(source_path, ffprobe_path=ffprobe_path)
            # requested_rungs is set by finalize() before a job is ever
            # enqueued (0040) — DEFAULT_RUNGS is a defensive fallback
            # only, not the normal path.
            rungs = (
                tuple(asset.requested_rungs)
                if asset.requested_rungs
                else ffmpeg_service.DEFAULT_RUNGS
            )

            log.info("transcode_started", video_asset_id=str(video_asset_id), rungs=rungs)
            await run_transcode(
                source_path,
                output_dir,
                rungs,
                probe,
                ffmpeg_path=ffmpeg_path,
                on_progress=on_progress,
            )

            for file in sorted(output_dir.iterdir()):
                if not file.is_file():
                    continue
                key = f"{_object_prefix(asset.id)}/{file.name}"
                await storage.upload_object(
                    Container.PRIVATE_CONTENT,
                    key,
                    file.read_bytes(),
                    content_type=_content_type_for(file.name),
                )

            asset.duration_seconds = round(probe.duration_seconds)
            asset.playlist_object_key = f"{_object_prefix(asset.id)}/master.m3u8"
            asset.renditions = [{"resolution": r, **ffmpeg_service.LADDER[r]} for r in rungs]
            asset.state = "ready"
            job.state = "ready"
            job.progress_pct = 100
            job.finished_at = datetime.now(UTC)
            log.info("transcode_ready", video_asset_id=str(video_asset_id))
        except (TranscodeFailed, ffmpeg_service.FfmpegError) as exc:
            asset.state = "failed"
            job.state = FAILED_STATE
            job.error = str(exc)
            job.finished_at = datetime.now(UTC)
            log.error("transcode_failed", video_asset_id=str(video_asset_id), error=str(exc))
        except asyncio.CancelledError:
            # The worker cancels this on its job timeout, and a shutdown
            # cancels it too. Without this the asset stayed `transcoding`
            # for ever: that state was committed before ffmpeg started,
            # nothing else ever writes it, and the operations screen only
            # lists *failed* jobs — so the asset was invisible to the one
            # screen meant to surface it (fable5.1 review H-5).
            #
            # `shield` because the commit is itself an await inside a
            # cancelled task: without it the rollback would be the last
            # thing that happened and the row would stay stuck anyway.
            asset.state = "failed"
            job.state = FAILED_STATE
            job.error = (
                "The transcode was cancelled before it finished — most likely the worker's "
                "job timeout. Re-upload or re-queue the asset to try again."
            )
            job.finished_at = datetime.now(UTC)
            log.error("transcode_cancelled", video_asset_id=str(video_asset_id))
            await asyncio.shield(session.commit())
            raise

        await session.commit()


__all__ = ["FAILED_STATE", "transcode_video_asset"]
