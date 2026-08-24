"""Podcast episode authoring and public playback (REQ-STORE-04).

Business logic lives in `src/services/podcasts.py` — this file is
routing, permission checks, and response construction only, the same
split `src/routers/courses.py` uses. `podcast:manage` gates every write,
matching `course:edit`'s "one permission across a content-authoring
subsystem" convention (`0026`'s migration docstring). The `/public/
podcasts*` routes need no permission at all — no auth, `TenantDep` only —
the same shape `courses.py`'s `/public/courses/{id}/curriculum` already
established for anonymous, unauthenticated marketing content.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Query, Request, UploadFile, status
from redis.asyncio import Redis

from src.core.config import Settings, get_settings
from src.core.deps import PrincipalDep, RedisDep, SessionDep, SettingsDep, StorageDep, TenantDep
from src.core.errors import NotFound, TooManyAttempts
from src.core.net import client_ip
from src.models.podcast import PodcastEpisode
from src.schemas.podcasts import (
    PodcastEpisodeCreateRequest,
    PodcastEpisodeResponse,
    PodcastEpisodesPageResponse,
    PodcastEpisodeUpdateRequest,
    PodcastEventRequest,
    SpotifyLookupResponse,
)
from src.services import events, rate_limit, spotify
from src.services import podcasts as podcasts_service
from src.services.storage.base import StorageService

router = APIRouter(tags=["podcasts"])

# 03 §1.8 has no row specific to engagement-event logging; the general
# anonymous ceiling is reused rather than inventing an unreviewed limit
# (overall-review F5 — the endpoint had no rate limit at all before
# this, so an anonymous loop could both bloat the events table and
# directly inflate the new R2 dashboard's counts).
EVENT_RATE_LIMIT_PER_IP = 60
EVENT_RATE_LIMIT_WINDOW_SECONDS = 60


def _client_ip(request: Request) -> str | None:
    return client_ip(request, trust_x_forwarded_for=get_settings().trust_x_forwarded_for)


async def _enforce_event_rate_limit(redis: Redis, *, key_prefix: str, ip: str | None) -> None:
    if ip is None:
        return
    ok = await rate_limit.hit(
        redis,
        key=f"ratelimit:{key_prefix}:ip:{ip}",
        limit=EVENT_RATE_LIMIT_PER_IP,
        window_seconds=EVENT_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not ok:
        raise TooManyAttempts("Too many attempts. Try again later.")


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


async def _response(storage: StorageService, episode: PodcastEpisode) -> PodcastEpisodeResponse:
    return PodcastEpisodeResponse(
        id=str(episode.id),
        kind=episode.kind,
        slug=episode.slug,
        title=episode.title,
        description=episode.description,
        state=episode.state,
        show_notes=episode.show_notes,
        transcript=episode.transcript,
        related_course_id=str(episode.related_course_id) if episode.related_course_id else None,
        audio_url=await podcasts_service.resolve_audio_url(storage, episode),
        duration_seconds=episode.duration_seconds,
        cover_image_url=await podcasts_service.resolve_cover_image_url(storage, episode),
        external_platform=episode.external_platform,
        external_url=episode.external_url,
        curator_name=episode.curator_name,
        curator_note=episode.curator_note,
        position=episode.position,
    )


@router.get("/podcasts", response_model=PodcastEpisodesPageResponse)
async def list_podcast_episodes(
    principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> PodcastEpisodesPageResponse:
    principal.require("podcast:manage")
    episodes = await podcasts_service.list_episodes(session, tenant_id=principal.tenant_id)
    return PodcastEpisodesPageResponse(items=[await _response(storage, e) for e in episodes])


@router.post(
    "/podcasts", response_model=PodcastEpisodeResponse, status_code=status.HTTP_201_CREATED
)
async def create_podcast_episode(
    body: PodcastEpisodeCreateRequest,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
) -> PodcastEpisodeResponse:
    principal.require("podcast:manage")
    episode = await podcasts_service.create_episode(
        session,
        tenant_id=principal.tenant_id,
        kind=body.kind,
        title=body.title,
        slug=body.slug,
        description=body.description,
        show_notes=body.show_notes,
        transcript=body.transcript,
        related_course_id=_parse_uuid(body.related_course_id) if body.related_course_id else None,
        external_platform=body.external_platform,
        external_url=body.external_url,
        curator_name=body.curator_name,
        curator_note=body.curator_note,
    )
    return await _response(storage, episode)


@router.get(
    "/podcasts/spotify-lookup",
    response_model=SpotifyLookupResponse,
    summary="Prefill an episode form from a pasted Spotify URL",
)
async def spotify_lookup(
    principal: PrincipalDep, settings: SettingsDep, url: str = Query(...)
) -> SpotifyLookupResponse:
    # Registered ahead of GET /podcasts/{episode_id} on purpose — FastAPI/
    # Starlette matches routes in registration order, so a literal path
    # like this one must come before a parameterized sibling that would
    # otherwise swallow it (episode_id="spotify-lookup"). Caught by
    # test_podcasts.py's own lookup test, not spotted by inspection.
    principal.require("podcast:manage")
    result = await _spotify_lookup(url, settings)
    if result is None:
        return SpotifyLookupResponse(configured=False)
    return SpotifyLookupResponse(
        configured=True,
        title=result.title,
        description=result.description,
        duration_seconds=result.duration_seconds,
        cover_image_url=result.cover_image_url,
        embed_id=result.embed_id,
    )


async def _spotify_lookup(url: str, settings: Settings) -> spotify.SpotifyLookupResult | None:
    try:
        return await spotify.lookup_episode(url, settings=settings)
    except spotify.SpotifyLookupError as exc:
        raise NotFound(str(exc)) from exc


@router.get("/podcasts/{episode_id}", response_model=PodcastEpisodeResponse)
async def get_podcast_episode(
    episode_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> PodcastEpisodeResponse:
    principal.require("podcast:manage")
    episode = await podcasts_service.get_episode(
        session, tenant_id=principal.tenant_id, episode_id=_parse_uuid(episode_id)
    )
    return await _response(storage, episode)


@router.patch("/podcasts/{episode_id}", response_model=PodcastEpisodeResponse)
async def update_podcast_episode(
    episode_id: str,
    body: PodcastEpisodeUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
) -> PodcastEpisodeResponse:
    principal.require("podcast:manage")
    episode = await podcasts_service.update_episode(
        session,
        tenant_id=principal.tenant_id,
        episode_id=_parse_uuid(episode_id),
        title=body.title,
        description=body.description,
        show_notes=body.show_notes,
        transcript=body.transcript,
        related_course_id=_parse_uuid(body.related_course_id) if body.related_course_id else None,
        external_platform=body.external_platform,
        external_url=body.external_url,
        curator_name=body.curator_name,
        curator_note=body.curator_note,
        position=body.position,
    )
    return await _response(storage, episode)


@router.post("/podcasts/{episode_id}/publish", response_model=PodcastEpisodeResponse)
async def publish_podcast_episode(
    episode_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> PodcastEpisodeResponse:
    principal.require("podcast:manage")
    episode = await podcasts_service.publish_episode(
        session, tenant_id=principal.tenant_id, episode_id=_parse_uuid(episode_id)
    )
    return await _response(storage, episode)


@router.post("/podcasts/{episode_id}/unpublish", response_model=PodcastEpisodeResponse)
async def unpublish_podcast_episode(
    episode_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> PodcastEpisodeResponse:
    principal.require("podcast:manage")
    episode = await podcasts_service.unpublish_episode(
        session, tenant_id=principal.tenant_id, episode_id=_parse_uuid(episode_id)
    )
    return await _response(storage, episode)


@router.post(
    "/podcasts/{episode_id}/audio",
    response_model=PodcastEpisodeResponse,
    summary="Upload self-hosted audio for an authored episode",
)
async def upload_podcast_audio(
    episode_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> PodcastEpisodeResponse:
    principal.require("podcast:manage")
    data = await file.read()
    episode = await podcasts_service.upload_audio(
        session,
        storage,
        settings,
        tenant_id=principal.tenant_id,
        episode_id=_parse_uuid(episode_id),
        data=data,
        filename=file.filename or "audio",
        content_type=file.content_type,
    )
    return await _response(storage, episode)


@router.get(
    "/public/podcasts",
    response_model=PodcastEpisodesPageResponse,
    summary="Published podcast episodes, no auth required",
)
async def list_public_podcast_episodes(
    session: SessionDep, tenant: TenantDep, storage: StorageDep
) -> PodcastEpisodesPageResponse:
    episodes = await podcasts_service.list_published_episodes(session, tenant_id=tenant.id)
    return PodcastEpisodesPageResponse(items=[await _response(storage, e) for e in episodes])


@router.get(
    "/public/podcasts/{slug}",
    response_model=PodcastEpisodeResponse,
    summary="A published podcast episode, no auth required",
)
async def get_public_podcast_episode(
    slug: str, session: SessionDep, tenant: TenantDep, storage: StorageDep
) -> PodcastEpisodeResponse:
    episode = await podcasts_service.get_published_episode(session, tenant_id=tenant.id, slug=slug)
    return await _response(storage, episode)


@router.post(
    "/public/podcasts/{slug}/events",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Log a podcast engagement event (play/progress/CTA-click), no auth required",
)
async def log_podcast_event(
    request: Request,
    slug: str,
    body: PodcastEventRequest,
    session: SessionDep,
    tenant: TenantDep,
    redis: RedisDep,
) -> None:
    await _enforce_event_rate_limit(redis, key_prefix="podcast-events", ip=_client_ip(request))
    if body.event_name not in podcasts_service.ALLOWED_PODCAST_EVENT_NAMES:
        raise NotFound("Unknown event name.")
    episode = await podcasts_service.get_published_episode(session, tenant_id=tenant.id, slug=slug)
    properties = {
        "episode_id": str(episode.id),
        "kind": episode.kind,
        "percent_complete": body.percent_complete,
        "position_seconds": body.position_seconds,
        "source": body.source,
    }
    await events.record(
        session,
        tenant_id=tenant.id,
        event_name=body.event_name,
        # Only the fields this particular event actually carries — most
        # of the six podcast.* events leave two or three of these unset,
        # and writing them as explicit JSONB nulls on every row was pure
        # bloat (overall-review I5).
        properties={k: v for k, v in properties.items() if v is not None},
    )


__all__ = ["router"]
