"""Recommendation authoring and publishing (`docs/research/resources-hub-
design.md` §3). Structurally the same shape as `services/articles.py`, one
size smaller — no body, no reading time, no slug.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.recommendation import Recommendation


class RecommendationError(AppError):
    """A refusal in recommendation authoring — currently just an invalid
    `url`, the same `javascript:`/`data:` refusal `services/podcasts.py`
    enforces on `external_url` for the identical reason: this field is
    rendered back out as a raw `<a href>` on the public resources page."""

    code = "RECOMMENDATION_ERROR"


def _validate_url(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        raise RecommendationError("url must be an http:// or https:// link.")


async def create_recommendation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    url: str,
    source_name: str | None,
    curator_name: str | None,
    curator_note: str | None,
    related_course_id: uuid.UUID | None,
) -> Recommendation:
    _validate_url(url)
    position = (
        await session.execute(
            select(func.count()).select_from(Recommendation).where(
                Recommendation.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    recommendation = Recommendation(
        id=uuid7(),
        tenant_id=tenant_id,
        title=title,
        url=url,
        source_name=source_name,
        curator_name=curator_name,
        curator_note=curator_note,
        related_course_id=related_course_id,
        position=position,
    )
    session.add(recommendation)
    await session.flush()
    return recommendation


async def get_recommendation(
    session: AsyncSession, *, tenant_id: uuid.UUID, recommendation_id: uuid.UUID
) -> Recommendation:
    recommendation = await session.get(Recommendation, recommendation_id)
    if recommendation is None or recommendation.tenant_id != tenant_id:
        raise NotFound("No such recommendation.")
    return recommendation


async def list_recommendations(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Recommendation]:
    """Admin listing — every state."""
    stmt = (
        select(Recommendation)
        .where(Recommendation.tenant_id == tenant_id)
        .order_by(Recommendation.position, Recommendation.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_published_recommendations(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Recommendation]:
    stmt = (
        select(Recommendation)
        .where(Recommendation.tenant_id == tenant_id, Recommendation.state == "published")
        .order_by(Recommendation.position, Recommendation.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_recommendation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    title: str | None = None,
    url: str | None = None,
    source_name: str | None = None,
    curator_name: str | None = None,
    curator_note: str | None = None,
    related_course_id: uuid.UUID | None = None,
    position: int | None = None,
) -> Recommendation:
    recommendation = await get_recommendation(
        session, tenant_id=tenant_id, recommendation_id=recommendation_id
    )
    if title is not None:
        recommendation.title = title
    if url is not None:
        _validate_url(url)
        recommendation.url = url
    if source_name is not None:
        recommendation.source_name = source_name
    if curator_name is not None:
        recommendation.curator_name = curator_name
    if curator_note is not None:
        recommendation.curator_note = curator_note
    if related_course_id is not None:
        recommendation.related_course_id = related_course_id
    if position is not None:
        recommendation.position = position
    await session.flush()
    return recommendation


async def publish_recommendation(
    session: AsyncSession, *, tenant_id: uuid.UUID, recommendation_id: uuid.UUID
) -> Recommendation:
    recommendation = await get_recommendation(
        session, tenant_id=tenant_id, recommendation_id=recommendation_id
    )
    recommendation.state = "published"
    await session.flush()
    return recommendation


async def unpublish_recommendation(
    session: AsyncSession, *, tenant_id: uuid.UUID, recommendation_id: uuid.UUID
) -> Recommendation:
    recommendation = await get_recommendation(
        session, tenant_id=tenant_id, recommendation_id=recommendation_id
    )
    recommendation.state = "draft"
    await session.flush()
    return recommendation


__all__ = [
    "RecommendationError",
    "create_recommendation",
    "get_recommendation",
    "list_published_recommendations",
    "list_recommendations",
    "publish_recommendation",
    "unpublish_recommendation",
    "update_recommendation",
]
