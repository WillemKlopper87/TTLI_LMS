"""Podcast episode authoring, publishing, and self-hosted audio upload
(REQ-STORE-04, `docs/research/podcast-platform-integration.md`).

Deliberately does **not** reuse `services/media/{ffmpeg,transcoder,
pipeline}.py`'s transcode ladder — that pipeline exists for premium,
gated, anti-bypass-sensitive video (adaptive bitrate, seek-ceiling
enforcement, watermarking), none of which applies to a podcast episode
meant to be freely, permanently playable marketing content. A podcast
upload gets one `ffprobe` call for `duration_seconds` and a direct store
to `Container.PUBLIC_MARKETING` — no rendition ladder, no `transcode_jobs`
row, no arq job. See the research doc §2 for the full reasoning.

`kind='curated'` episodes are embed-only by design (no `audio_object_key`,
`upload_audio` refuses them) — TTLI doesn't own a third party's audio and
has no right to re-host it.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.errors import AppError, NotFound, ServiceUnavailable
from src.core.ids import uuid7
from src.models.podcast import PodcastEpisode
from src.services import antivirus, spotify
from src.services.media import ffmpeg as ffmpeg_service
from src.services.storage.base import Container, StorageService

_SLUG_RE = re.compile(r"[^a-z0-9]+")
PODCAST_KIND_VALUES = ("authored", "curated")


class PodcastError(AppError):
    """A refusal in podcast authoring — an invalid kind/field combination,
    an unpublishable episode, or an upload rejected by a check this
    module enforces."""

    code = "PODCAST_ERROR"


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "episode"


async def _unique_slug(session: AsyncSession, *, tenant_id: uuid.UUID, title: str) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while (
        await session.execute(
            select(PodcastEpisode.id).where(
                PodcastEpisode.tenant_id == tenant_id, PodcastEpisode.slug == slug
            )
        )
    ).scalar_one_or_none() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _derive_embed_id(external_url: str | None) -> str | None:
    """Parsed once at write time, not on every render — the iframe's own
    `src` attribute reads `external_embed_id` directly rather than
    re-parsing `external_url`. Only Spotify URLs resolve today; any other
    URL (Apple Podcasts, etc.) is stored as-is with no embed ID, since
    only Spotify has the well-known `/episode/{id}` embed path this
    project builds an iframe for (`SpotifyEmbed.tsx`)."""
    if not external_url:
        return None
    return spotify.parse_episode_id(external_url)


def _validate_external_url(external_url: str | None) -> None:
    """`external_url` is rendered back out as a raw `<a href>` on the
    public episode page (`app/podcasts/[slug]/page.tsx`) — refusing
    anything but `http(s)://` here is what stops a `javascript:`/`data:`
    URL from ever reaching that anchor tag in the first place. The
    frontend has its own defensive scheme check too (belt and braces,
    the same layered posture the Payfast webhook's signature+confirm+
    amount checks already established) — this is the authoritative one,
    since `podcast:manage` gates who can set this field, not who can
    read it back."""
    if not external_url:
        return
    if not external_url.startswith(("http://", "https://")):
        raise PodcastError("external_url must be an http:// or https:// link.")


def _validate_kind_fields(*, kind: str, external_url: str | None, curator_name: str | None) -> None:
    if kind not in PODCAST_KIND_VALUES:
        raise PodcastError(f"kind must be one of {PODCAST_KIND_VALUES!r}.")
    if kind == "curated" and (not external_url or not curator_name):
        raise PodcastError("A curated episode needs both external_url and curator_name.")


async def create_episode(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kind: str,
    title: str,
    slug: str | None,
    description: str | None,
    show_notes: str | None,
    transcript: str | None,
    related_course_id: uuid.UUID | None,
    external_platform: str | None,
    external_url: str | None,
    curator_name: str | None,
    curator_note: str | None,
) -> PodcastEpisode:
    _validate_kind_fields(kind=kind, external_url=external_url, curator_name=curator_name)
    _validate_external_url(external_url)
    position = (
        await session.execute(
            select(func.count())
            .select_from(PodcastEpisode)
            .where(PodcastEpisode.tenant_id == tenant_id)
        )
    ).scalar_one()
    episode = PodcastEpisode(
        id=uuid7(),
        tenant_id=tenant_id,
        kind=kind,
        slug=slug or await _unique_slug(session, tenant_id=tenant_id, title=title),
        title=title,
        description=description,
        show_notes=show_notes,
        transcript=transcript,
        related_course_id=related_course_id,
        external_platform=external_platform,
        external_url=external_url,
        external_embed_id=_derive_embed_id(external_url),
        curator_name=curator_name,
        curator_note=curator_note,
        position=position,
    )
    session.add(episode)
    await session.flush()
    return episode


async def get_episode(
    session: AsyncSession, *, tenant_id: uuid.UUID, episode_id: uuid.UUID
) -> PodcastEpisode:
    episode = await session.get(PodcastEpisode, episode_id)
    if episode is None or episode.tenant_id != tenant_id:
        raise NotFound("No such podcast episode.")
    return episode


async def list_episodes(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[PodcastEpisode]:
    """Admin listing — every state, curated and authored alike."""
    stmt = (
        select(PodcastEpisode)
        .where(PodcastEpisode.tenant_id == tenant_id)
        .order_by(PodcastEpisode.position, PodcastEpisode.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_published_episodes(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[PodcastEpisode]:
    stmt = (
        select(PodcastEpisode)
        .where(PodcastEpisode.tenant_id == tenant_id, PodcastEpisode.state == "published")
        .order_by(PodcastEpisode.position, PodcastEpisode.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_published_episode(
    session: AsyncSession, *, tenant_id: uuid.UUID, slug: str
) -> PodcastEpisode:
    stmt = select(PodcastEpisode).where(
        PodcastEpisode.tenant_id == tenant_id,
        PodcastEpisode.slug == slug,
        PodcastEpisode.state == "published",
    )
    episode = (await session.execute(stmt)).scalars().first()
    if episode is None:
        raise NotFound("No such podcast episode.")
    return episode


async def update_episode(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    episode_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    show_notes: str | None = None,
    transcript: str | None = None,
    related_course_id: uuid.UUID | None = None,
    external_platform: str | None = None,
    external_url: str | None = None,
    curator_name: str | None = None,
    curator_note: str | None = None,
    position: int | None = None,
) -> PodcastEpisode:
    episode = await get_episode(session, tenant_id=tenant_id, episode_id=episode_id)
    if title is not None:
        episode.title = title
    if description is not None:
        episode.description = description
    if show_notes is not None:
        episode.show_notes = show_notes
    if transcript is not None:
        episode.transcript = transcript
    if related_course_id is not None:
        episode.related_course_id = related_course_id
    if external_platform is not None:
        episode.external_platform = external_platform
    if external_url is not None:
        _validate_external_url(external_url)
        episode.external_url = external_url
        episode.external_embed_id = _derive_embed_id(external_url)
    if curator_name is not None:
        episode.curator_name = curator_name
    if curator_note is not None:
        episode.curator_note = curator_note
    if position is not None:
        episode.position = position
    await session.flush()
    return episode


async def publish_episode(
    session: AsyncSession, *, tenant_id: uuid.UUID, episode_id: uuid.UUID
) -> PodcastEpisode:
    episode = await get_episode(session, tenant_id=tenant_id, episode_id=episode_id)
    if episode.kind == "curated":
        if not episode.external_url or not episode.curator_name:
            raise PodcastError("A curated episode needs external_url and curator_name to publish.")
    elif not episode.audio_object_key and not episode.external_url:
        raise PodcastError(
            "An authored episode needs uploaded audio or a cross-post link before it can publish."
        )
    episode.state = "published"
    await session.flush()
    return episode


async def unpublish_episode(
    session: AsyncSession, *, tenant_id: uuid.UUID, episode_id: uuid.UUID
) -> PodcastEpisode:
    episode = await get_episode(session, tenant_id=tenant_id, episode_id=episode_id)
    episode.state = "draft"
    await session.flush()
    return episode


async def upload_audio(
    session: AsyncSession,
    storage: StorageService,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    episode_id: uuid.UUID,
    data: bytes,
    filename: str,
    content_type: str | None,
) -> PodcastEpisode:
    episode = await get_episode(session, tenant_id=tenant_id, episode_id=episode_id)
    if episode.kind != "authored":
        raise PodcastError("Only an authored episode can have self-hosted audio uploaded.")

    # Same fail-closed virus-scanning rule every other upload in this
    # project follows (REQ-BYPASS-08) — a content author's upload is not
    # trusted any more than a learner's.
    try:
        result = await antivirus.scan(data, settings=settings)
    except antivirus.ScanUnavailable as exc:
        raise ServiceUnavailable("The virus scanner is unavailable. Try again shortly.") from exc
    if not result.clean:
        raise PodcastError(f"That file was rejected by the virus scanner ({result.signature}).")

    ffprobe_path = ffmpeg_service.resolve_binary("ffprobe", override=settings.ffprobe_path)
    with tempfile.TemporaryDirectory(prefix="ttli-podcast-") as tmp:
        source_path = Path(tmp) / (filename or "audio")
        source_path.write_bytes(data)
        probe = await ffmpeg_service.probe_source(source_path, ffprobe_path=ffprobe_path)

    key = f"podcast-episodes/{episode.id}/{filename or 'audio'}"
    await storage.ensure_container(Container.PUBLIC_MARKETING)
    await storage.upload_object(Container.PUBLIC_MARKETING, key, data, content_type=content_type)

    episode.audio_object_key = key
    episode.duration_seconds = round(probe.duration_seconds)
    await session.flush()
    return episode


async def resolve_audio_url(storage: StorageService, episode: PodcastEpisode) -> str | None:
    if not episode.audio_object_key:
        return None
    return await storage.get_public_url(Container.PUBLIC_MARKETING, episode.audio_object_key)


async def resolve_cover_image_url(storage: StorageService, episode: PodcastEpisode) -> str | None:
    if not episode.cover_image_object_key:
        return None
    return await storage.get_public_url(Container.PUBLIC_MARKETING, episode.cover_image_object_key)


__all__ = [
    "PodcastError",
    "create_episode",
    "get_episode",
    "get_published_episode",
    "list_episodes",
    "list_published_episodes",
    "publish_episode",
    "resolve_audio_url",
    "resolve_cover_image_url",
    "unpublish_episode",
    "update_episode",
    "upload_audio",
]
