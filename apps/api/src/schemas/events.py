"""Request bodies for public, unauthenticated event-logging endpoints
that aren't tied to one domain resource — contrast articles.py's
ArticleEventRequest and podcasts.py's PodcastEventRequest, which are."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PageViewRequest(BaseModel):
    """A pageview on a public marketing page (01_PRD.md §5.11: first-
    party analytics, no third-party tracker). `path` is validated as
    app-relative so this endpoint can't become an arbitrary-string
    sink for whatever a caller sends."""

    path: str = Field(max_length=512)
    referrer: str | None = Field(default=None, max_length=512)

    @field_validator("path")
    @classmethod
    def path_must_be_relative(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("path must be an app-relative path starting with a single /")
        return value
