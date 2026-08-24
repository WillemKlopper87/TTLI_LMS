from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.course import CONTENT_STATE_VALUES

PODCAST_KIND_VALUES = ("authored", "curated")


class PodcastEpisodeCreateRequest(BaseModel):
    kind: str = Field(pattern="^(" + "|".join(PODCAST_KIND_VALUES) + ")$")
    title: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    description: str | None = None
    show_notes: str | None = None
    transcript: str | None = None
    related_course_id: str | None = None
    external_platform: str | None = None
    external_url: str | None = None
    curator_name: str | None = None
    curator_note: str | None = None


class PodcastEpisodeUpdateRequest(BaseModel):
    """Every field `None` means "leave unchanged" — matches
    `CourseUpdateRequest`'s convention. `kind` is not updatable: an
    episode's audio/curation shape is a create-time decision, not
    something to flip after the fact (`services/podcasts.py` refuses to
    change it)."""

    title: str | None = None
    description: str | None = None
    show_notes: str | None = None
    transcript: str | None = None
    related_course_id: str | None = None
    external_platform: str | None = None
    external_url: str | None = None
    curator_name: str | None = None
    curator_note: str | None = None
    position: int | None = Field(default=None, ge=0)


class PodcastEpisodeResponse(BaseModel):
    id: str
    kind: str
    slug: str
    title: str
    description: str | None
    state: str = Field(pattern="^(" + "|".join(CONTENT_STATE_VALUES) + ")$")
    show_notes: str | None
    transcript: str | None
    related_course_id: str | None
    audio_url: str | None
    duration_seconds: int | None
    cover_image_url: str | None
    external_platform: str | None
    external_url: str | None
    curator_name: str | None
    curator_note: str | None
    position: int


class PodcastEpisodesPageResponse(BaseModel):
    items: list[PodcastEpisodeResponse]


class SpotifyLookupResponse(BaseModel):
    """`configured=False` means no `spotify_client_id` is set for this
    deployment — the same graceful-degradation shape
    `services/payments/payfast.py` established for an unconfigured
    provider. The caller falls back to manual entry, not an error."""

    configured: bool
    title: str | None = None
    description: str | None = None
    duration_seconds: int | None = None
    cover_image_url: str | None = None
    embed_id: str | None = None


class PodcastEventRequest(BaseModel):
    # max_length is a cheap belt (overall-review F5) — event_name is
    # already semantically bounded by the allowed-set check in
    # log_podcast_event, and source has no allowed-set at all.
    event_name: str = Field(max_length=64)
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    position_seconds: int | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=64)


__all__ = [
    "PODCAST_KIND_VALUES",
    "PodcastEpisodeCreateRequest",
    "PodcastEpisodeResponse",
    "PodcastEpisodeUpdateRequest",
    "PodcastEpisodesPageResponse",
    "PodcastEventRequest",
    "SpotifyLookupResponse",
]
