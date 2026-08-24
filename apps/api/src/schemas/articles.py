from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.course import CONTENT_STATE_VALUES


class ArticleCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    dek: str | None = None
    body: str = Field(min_length=1)
    author_name: str | None = None
    related_course_id: str | None = None


class ArticleUpdateRequest(BaseModel):
    """Every field `None` means "leave unchanged" — matches
    `PodcastEpisodeUpdateRequest`'s convention."""

    title: str | None = None
    dek: str | None = None
    body: str | None = None
    author_name: str | None = None
    related_course_id: str | None = None
    position: int | None = Field(default=None, ge=0)


class ArticleResponse(BaseModel):
    id: str
    slug: str
    title: str
    dek: str | None
    body: str
    cover_image_url: str | None
    author_name: str | None
    related_course_id: str | None
    state: str = Field(pattern="^(" + "|".join(CONTENT_STATE_VALUES) + ")$")
    published_at: str | None
    reading_minutes: int | None
    position: int


class ArticlesPageResponse(BaseModel):
    items: list[ArticleResponse]


class ArticleEventRequest(BaseModel):
    """R3 (docs/BACKLOG.md; docs/research/resources-hub-design.md §4
    decision 3) — "at least a viewed event for symmetry" with podcasts'
    listen-stat set. One event today, not six: the shape still mirrors
    `PodcastEventRequest`'s `event_name` field so a later pass can add
    more without a breaking change."""

    event_name: str


__all__ = [
    "ArticleCreateRequest",
    "ArticleEventRequest",
    "ArticleResponse",
    "ArticleUpdateRequest",
    "ArticlesPageResponse",
]
