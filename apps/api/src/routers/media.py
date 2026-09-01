"""The media pipeline's HTTP surface (03 §6.7, 06 §3, REQ-BYPASS-08).

Upload and lesson-attach are gated on `course:edit` — a content-author
action, not a learner one. Playback is gated on the caller holding a real
enrolment for the course the video's lesson belongs to
(services/enrolment.py::has_access_to_video), checked before a URL is
ever minted. The HLS-serving route underneath a minted playback URL is
deliberately unauthenticated in the normal sense — media players cannot
set headers on segment requests, so the short-lived, single-asset-bound
token in the query string is the only credential it accepts (06 §3.2).
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy import select

from src.core.deps import CryptoDep, PrincipalDep, RedisDep, SessionDep, SettingsDep, StorageDep
from src.core.errors import AppError, Forbidden, NotFound, ServiceUnavailable
from src.core.ids import uuid7
from src.core.object_keys import build_object_key
from src.core.queue import get_queue
from src.models.course import Course, Lesson
from src.models.media import VideoAsset
from src.models.tenant import Tenant
from src.models.user import User
from src.schemas.media import (
    PlaybackResponse,
    VideoAssetResponse,
    VideoAssetsPageResponse,
    VideoFinalizeRequest,
    WatermarkPayload,
)
from src.services import antivirus
from src.services import enrolment as enrolment_service
from src.services.media import ffmpeg as ffmpeg_service
from src.services.media import playback
from src.services.media import video_settings as video_settings_service
from src.services.storage import Container
from src.services.storage.base import ObjectNotFound

router = APIRouter(tags=["media"])

TRANSCODE_JOB = "transcode_video_job"


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _video_asset_response(
    asset: VideoAsset, *, default_rungs: list[str] | None = None, allow_bypass: bool | None = None
) -> VideoAssetResponse:
    """default_rungs/allow_bypass are only meaningful while state="draft"
    (the decision panel's pre-fill) — omitted on list/get calls for an
    already-decided asset, where they'd otherwise have to be re-resolved
    against a course/tenant that no longer matters for that asset."""
    return VideoAssetResponse(
        id=str(asset.id),
        state=asset.state,
        duration_seconds=asset.duration_seconds,
        has_captions=asset.caption_object_key is not None,
        delivery_mode=asset.delivery_mode,
        source_filename=asset.source_filename,
        source_size_bytes=asset.source_size_bytes,
        estimated_sizes=dict(asset.estimated_sizes or {}),
        default_rungs=default_rungs if default_rungs is not None else [],
        allow_bypass=allow_bypass if allow_bypass is not None else True,
        requested_rungs=list(asset.requested_rungs or []),
    )


@router.get(
    "/video-assets", response_model=VideoAssetsPageResponse, summary="List uploaded video assets"
)
async def list_video_assets(
    principal: PrincipalDep, session: SessionDep
) -> VideoAssetsPageResponse:
    principal.require("course:edit")
    stmt = select(VideoAsset).order_by(VideoAsset.id.desc())
    assets = (await session.execute(stmt)).scalars().all()
    return VideoAssetsPageResponse(items=[_video_asset_response(a) for a in assets])


@router.post(
    "/video-assets",
    response_model=VideoAssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a source video, awaiting a transcode/as-is decision (0040)",
)
async def upload_video_asset(
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
    course_id: str | None = Form(None),
) -> VideoAssetResponse:
    """Phase 1 of the two-phase upload (0040): scan, store, probe, and
    estimate — then stop and let the admin decide, rather than
    immediately enqueueing a transcode with a hardcoded rung selection.
    `course_id` is advisory only (the admin UI already knows which
    course/lesson it's uploading into); it lets the decision panel
    pre-fill from that course's video settings before anything has been
    decided, and is re-checked at finalize time for the same reason.
    """
    principal.require("course:edit")
    data = await file.read()

    # Same fail-closed virus-scanning rule as the payment-proof upload
    # (REQ-BYPASS-08) — a source video is exactly the kind of upload it
    # protects against, and there is no reason to trust content-author
    # uploads more than learner ones.
    try:
        result = await antivirus.scan(data, settings=settings)
    except antivirus.ScanUnavailable as exc:
        raise ServiceUnavailable("The virus scanner is unavailable. Try again shortly.") from exc
    if not result.clean:
        raise AppError(
            "That file was rejected by the virus scanner and was not stored.",
            {"signature": result.signature},
        )

    asset_id = uuid7()
    source_key = build_object_key(
        "video-assets", asset_id, "source", filename=file.filename, fallback="source"
    )
    await storage.ensure_container(Container.PRIVATE_CONTENT)
    await storage.upload_object(
        Container.PRIVATE_CONTENT, source_key, data, content_type=file.content_type
    )

    # ffprobe needs a real file on disk, not bytes in memory — reuse the
    # bytes already read above rather than a second storage round-trip.
    ffprobe_path = ffmpeg_service.resolve_binary("ffprobe", override=settings.ffprobe_path)
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(data)
        tmp.flush()
        probe = await ffmpeg_service.probe_source(Path(tmp.name), ffprobe_path=ffprobe_path)

    course_uuid = _parse_uuid(course_id) if course_id else None
    course = await session.get(Course, course_uuid) if course_uuid else None
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:  # pragma: no cover - the request already resolved this tenant
        raise NotFound("No such tenant.")
    default_rungs = video_settings_service.resolve_default_rungs(course, tenant)
    allow_bypass = video_settings_service.resolve_allow_bypass(course, tenant)
    estimated_sizes = video_settings_service.estimate_sizes(
        probe.duration_seconds, has_audio=probe.has_audio
    )

    asset = VideoAsset(
        id=asset_id,
        source_object_key=source_key,
        state="draft",
        duration_seconds=round(probe.duration_seconds),
        source_content_type=file.content_type,
        source_filename=file.filename,
        source_size_bytes=len(data),
        estimated_sizes=estimated_sizes,
        course_id=course_uuid,
    )
    session.add(asset)
    await session.flush()

    return _video_asset_response(asset, default_rungs=default_rungs, allow_bypass=allow_bypass)


@router.post(
    "/video-assets/{video_asset_id}/finalize",
    response_model=VideoAssetResponse,
    summary="Decide how a draft video asset is delivered (0040)",
)
async def finalize_video_asset(
    video_asset_id: str,
    body: VideoFinalizeRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> VideoAssetResponse:
    principal.require("course:edit")
    asset = await session.get(VideoAsset, _parse_uuid(video_asset_id))
    if asset is None:
        raise NotFound("No such video asset.")
    if asset.state != "draft":
        raise AppError("This video asset has already been finalized.")

    if body.mode == "as_is":
        course = await session.get(Course, asset.course_id) if asset.course_id else None
        tenant = await session.get(Tenant, principal.tenant_id)
        if tenant is None:  # pragma: no cover - the request already resolved this tenant
            raise NotFound("No such tenant.")
        if not video_settings_service.resolve_allow_bypass(course, tenant):
            raise AppError("This course requires transcoding — uploading as-is isn't allowed.")
        if (asset.source_size_bytes or 0) > settings.bypass_max_size_bytes:
            raise AppError(
                "This file is too large to serve as-is.",
                {"max_bytes": settings.bypass_max_size_bytes},
            )
        asset.delivery_mode = "progressive"
        asset.playlist_object_key = None
        asset.state = "ready"
        await session.flush()
        return _video_asset_response(asset)

    rungs = body.rungs
    unknown = [r for r in rungs if r not in ffmpeg_service.LADDER]
    if not rungs or unknown:
        raise AppError(
            "Choose at least one valid resolution.",
            {"unknown_rungs": unknown} if unknown else {},
        )
    asset.requested_rungs = rungs
    asset.delivery_mode = "hls"
    asset.state = "uploaded"
    await session.flush()

    await get_queue().enqueue_job(TRANSCODE_JOB, video_asset_id=str(asset.id))

    return _video_asset_response(asset)


@router.post(
    "/video-assets/{video_asset_id}/captions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Upload a WebVTT caption track for a video asset (REQ-LMS-07)",
)
async def upload_captions(
    video_asset_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    file: UploadFile = File(...),
) -> None:
    # Human-authored WebVTT upload, not automatic transcription — no ASR
    # pipeline exists in this project, and fabricating caption text for
    # content nobody wrote would be worse than no captions at all.
    principal.require("course:edit")
    asset = await session.get(VideoAsset, _parse_uuid(video_asset_id))
    if asset is None:
        raise NotFound("No such video asset.")
    data = await file.read()
    if not data.lstrip().startswith(b"WEBVTT"):
        raise AppError("That file is not a valid WebVTT (.vtt) caption track.")

    key = f"video-assets/{video_asset_id}/captions.vtt"
    await storage.ensure_container(Container.PRIVATE_CONTENT)
    await storage.upload_object(Container.PRIVATE_CONTENT, key, data, content_type="text/vtt")
    asset.caption_object_key = key
    await session.flush()


@router.get(
    "/video-assets/{video_asset_id}",
    response_model=VideoAssetResponse,
    summary="Check a video asset's transcode state",
)
async def get_video_asset(
    video_asset_id: str, principal: PrincipalDep, session: SessionDep
) -> VideoAssetResponse:
    principal.require("course:edit")
    asset = await session.get(VideoAsset, _parse_uuid(video_asset_id))
    if asset is None:
        raise NotFound("No such video asset.")
    if asset.state != "draft":
        return _video_asset_response(asset)
    # Still deciding — re-resolve the defaults so a page reload doesn't
    # lose the decision panel's pre-fill (e.g. the admin navigated away
    # mid-decision and came back).
    course = await session.get(Course, asset.course_id) if asset.course_id else None
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:  # pragma: no cover - the request already resolved this tenant
        raise NotFound("No such tenant.")
    default_rungs = video_settings_service.resolve_default_rungs(course, tenant)
    allow_bypass = video_settings_service.resolve_allow_bypass(course, tenant)
    return _video_asset_response(asset, default_rungs=default_rungs, allow_bypass=allow_bypass)


@router.post(
    "/lessons/{lesson_id}/video",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Attach an uploaded video asset to a lesson",
)
async def attach_video_to_lesson(
    lesson_id: str, video_asset_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    # A narrow, single-field write, same as the quiz/survey/assignment
    # attach endpoints in routers/assessment.py — general lesson CRUD
    # lives in routers/courses.py, this stays a separate, focused
    # primitive rather than folding video attachment into that surface.
    principal.require("course:edit")
    lesson = await session.get(Lesson, _parse_uuid(lesson_id))
    if lesson is None:
        raise NotFound("No such lesson.")
    asset = await session.get(VideoAsset, _parse_uuid(video_asset_id))
    if asset is None:
        raise NotFound("No such video asset.")
    lesson.video_asset_id = asset.id
    lesson.activity_type = "video"
    await session.flush()


@router.get(
    "/media/{video_asset_id}/playback",
    response_model=PlaybackResponse,
    summary="Mint a short-lived signed playlist URL (03 §6.7)",
)
async def get_playback(
    video_asset_id: str,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    crypto: CryptoDep,
) -> PlaybackResponse:
    asset_uuid = _parse_uuid(video_asset_id)
    asset = await session.get(VideoAsset, asset_uuid)
    if asset is None or asset.state != "ready":
        raise NotFound("No such playable video.")

    # Entitlement checked before the URL is ever minted (03 §6.7) — never
    # cached, so a revoked entitlement takes effect on the very next call.
    # course:edit short-circuits the entitlement check: an author
    # previewing their own draft (the wizard's view-as-learner) holds no
    # enrolment. Learner tokens never carry course:edit, so the gate is
    # unchanged for every existing learner-facing call site.
    allowed = "course:edit" in principal.permissions or await enrolment_service.has_access_to_video(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        video_asset_id=asset_uuid,
    )
    if not allowed:
        raise Forbidden("You do not have access to this video.")

    token = await playback.mint(
        redis,
        user_id=principal.user_id,
        video_asset_id=asset_uuid,
        expires_in=settings.playback_url_expiry_seconds,
        max_concurrent_sessions=settings.max_concurrent_video_sessions,
    )

    user = await session.get(User, principal.user_id)
    email = crypto.decrypt(user.email_encrypted) if user is not None else "unknown"
    # REQ-LEAD-05: guest playback is watermarked as sample content, not
    # just traced by identity like a paying learner's — the only content
    # a guest can ever reach here is already access_level="public" (the
    # entitlement check above), so this never fires for real coursework.
    watermark_text = (
        f"SAMPLE · GUEST ACCESS · {email}"
        if user is not None and user.is_guest
        else f"{email} · {_client_ip(request)}"
    )

    # 0040's as-is bypass: a progressive asset has no HLS manifest at
    # all (playlist_object_key is None), so it gets a dedicated route
    # that serves the original file directly instead.
    if asset.delivery_mode == "progressive":
        playlist_url = f"media/{video_asset_id}/original?access_token={token}"
    else:
        playlist_url = f"media/{video_asset_id}/hls/master.m3u8?access_token={token}"

    return PlaybackResponse(
        # Relative to this API's own root (no /api/v1 prefix) — the BFF is
        # a web-tier concern (apps/web/app/api/bff/[...path]/route.ts maps
        # /api/bff/* to /api/v1/* 1:1), not something this service should
        # hardcode. The frontend prefixes this with /api/bff/ itself, the
        # same way it already builds every other bff fetch URL.
        playlist_url=playlist_url,
        captions_url=f"media/{video_asset_id}/hls/captions.vtt?access_token={token}"
        if asset.caption_object_key is not None
        else None,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.playback_url_expiry_seconds),
        watermark=WatermarkPayload(text=watermark_text, opacity=0.18),
        delivery_mode=asset.delivery_mode,
    )


@router.get(
    "/media/{video_asset_id}/original", summary="Serve the original file, as-is delivery (0040)"
)
async def get_original_file(
    video_asset_id: str,
    session: SessionDep,
    storage: StorageDep,
    redis: RedisDep,
    access_token: str = Query(...),
) -> Response:
    asset_uuid = _parse_uuid(video_asset_id)
    user_id = await playback.validate(redis, token=access_token, video_asset_id=asset_uuid)
    if user_id is None:
        raise Forbidden("This playback link has expired or is invalid.")

    asset = await session.get(VideoAsset, asset_uuid)
    if asset is None or asset.delivery_mode != "progressive":
        raise NotFound("No such file.")

    # The stored key, read directly off the row — not reconstructed via
    # build_object_key the way get_hls_file does, since the source file's
    # actual key (built at upload time from the original filename) isn't
    # guaranteed to match that reconstruction for arbitrary source
    # extensions.
    try:
        data = await storage.get_object(Container.PRIVATE_CONTENT, asset.source_object_key)
    except ObjectNotFound as exc:
        raise NotFound("No such file.") from exc

    media_type = asset.source_content_type or "application/octet-stream"
    return Response(content=data, media_type=media_type)


@router.get("/media/{video_asset_id}/hls/{filename}", summary="Serve one HLS manifest or segment")
async def get_hls_file(
    video_asset_id: str,
    filename: str,
    storage: StorageDep,
    redis: RedisDep,
    access_token: str = Query(...),
) -> Response:
    asset_uuid = _parse_uuid(video_asset_id)
    user_id = await playback.validate(redis, token=access_token, video_asset_id=asset_uuid)
    if user_id is None:
        raise Forbidden("This playback link has expired or is invalid.")

    # filename is never trusted as a path — it addresses one object under
    # this asset's own flat storage prefix, nothing else on the backend.
    if "/" in filename or ".." in filename:
        raise NotFound("No such file.")
    key = build_object_key("video-assets", video_asset_id, filename=filename, fallback="asset")

    try:
        data = await storage.get_object(Container.PRIVATE_CONTENT, key)
    except ObjectNotFound as exc:
        raise NotFound("No such file.") from exc

    if filename.endswith(".m3u8"):
        rewritten = playback.rewrite_manifest(data.decode("utf-8"), token=access_token)
        return Response(content=rewritten, media_type="application/vnd.apple.mpegurl")
    if filename.endswith(".mp4"):
        return Response(content=data, media_type="video/mp4")
    if filename.endswith(".vtt"):
        return Response(content=data, media_type="text/vtt")
    return Response(content=data, media_type="video/iso.segment")


__all__ = ["router"]
