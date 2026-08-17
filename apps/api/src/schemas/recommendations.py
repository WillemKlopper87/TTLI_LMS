from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.course import CONTENT_STATE_VALUES


class RecommendationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1)
    source_name: str | None = None
    curator_name: str | None = None
    curator_note: str | None = None
    related_course_id: str | None = None


class RecommendationUpdateRequest(BaseModel):
    """Every field `None` means "leave unchanged" — matches
    `ArticleUpdateRequest`'s convention."""

    title: str | None = None
    url: str | None = None
    source_name: str | None = None
    curator_name: str | None = None
    curator_note: str | None = None
    related_course_id: str | None = None
    position: int | None = Field(default=None, ge=0)


class RecommendationResponse(BaseModel):
    id: str
    title: str
    url: str
    source_name: str | None
    curator_name: str | None
    curator_note: str | None
    related_course_id: str | None
    state: str = Field(pattern="^(" + "|".join(CONTENT_STATE_VALUES) + ")$")
    position: int


class RecommendationsPageResponse(BaseModel):
    items: list[RecommendationResponse]


__all__ = [
    "RecommendationCreateRequest",
    "RecommendationResponse",
    "RecommendationUpdateRequest",
    "RecommendationsPageResponse",
]
