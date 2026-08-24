"""Article authoring and publishing (`docs/research/resources-hub-design.md`
§2). Structurally the same shape as `services/podcasts.py` minus the
audio-upload path — an article has no self-hosted media, only a markdown
`body` rendered client-side.

`reading_minutes` is computed once, at the transition to `published`, from
a ~200wpm heuristic — the same estimate `course_wizard.py` uses for lesson
duration. Recomputing on every read would be free either way, but pinning
it at publish time means an edit to a *draft* doesn't silently change a
number a reader already saw on a *live* article without an explicit
republish.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.article import Article
from src.services.storage.base import Container, StorageService

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_WORDS_PER_MINUTE = 200


class ArticleEventName:
    """R3 (docs/BACKLOG.md; resources-hub-design.md §4 decision 3) — the
    one event articles get "for symmetry" with podcasts' six, mirroring
    `services/podcasts.py::PodcastEventName`'s own placement (service
    layer, not the router, so a future reader — an analytics panel —
    can share the constant without depending on router internals)."""

    VIEWED = "article.viewed"


ALLOWED_ARTICLE_EVENT_NAMES = {ArticleEventName.VIEWED}


class ArticleError(AppError):
    """A refusal in article authoring — an unpublishable article (no
    body) or any other invalid state transition this module enforces."""

    code = "ARTICLE_ERROR"


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "article"


async def _unique_slug(session: AsyncSession, *, tenant_id: uuid.UUID, title: str) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while (
        await session.execute(
            select(Article.id).where(Article.tenant_id == tenant_id, Article.slug == slug)
        )
    ).scalar_one_or_none() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _reading_minutes(body: str) -> int:
    words = len(body.split())
    return max(1, round(words / _WORDS_PER_MINUTE))


async def create_article(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    slug: str | None,
    dek: str | None,
    body: str,
    author_name: str | None,
    related_course_id: uuid.UUID | None,
) -> Article:
    position = (
        await session.execute(
            select(func.count()).select_from(Article).where(Article.tenant_id == tenant_id)
        )
    ).scalar_one()
    article = Article(
        id=uuid7(),
        tenant_id=tenant_id,
        slug=slug or await _unique_slug(session, tenant_id=tenant_id, title=title),
        title=title,
        dek=dek,
        body=body,
        author_name=author_name,
        related_course_id=related_course_id,
        position=position,
    )
    session.add(article)
    await session.flush()
    return article


async def get_article(
    session: AsyncSession, *, tenant_id: uuid.UUID, article_id: uuid.UUID
) -> Article:
    article = await session.get(Article, article_id)
    if article is None or article.tenant_id != tenant_id:
        raise NotFound("No such article.")
    return article


async def list_articles(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Article]:
    """Admin listing — every state."""
    stmt = (
        select(Article)
        .where(Article.tenant_id == tenant_id)
        .order_by(Article.position, Article.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_published_articles(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Article]:
    stmt = (
        select(Article)
        .where(Article.tenant_id == tenant_id, Article.state == "published")
        .order_by(Article.published_at.desc().nullslast(), Article.position)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_published_article(
    session: AsyncSession, *, tenant_id: uuid.UUID, slug: str
) -> Article:
    stmt = select(Article).where(
        Article.tenant_id == tenant_id, Article.slug == slug, Article.state == "published"
    )
    article = (await session.execute(stmt)).scalars().first()
    if article is None:
        raise NotFound("No such article.")
    return article


async def update_article(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    article_id: uuid.UUID,
    title: str | None = None,
    dek: str | None = None,
    body: str | None = None,
    author_name: str | None = None,
    related_course_id: uuid.UUID | None = None,
    position: int | None = None,
) -> Article:
    article = await get_article(session, tenant_id=tenant_id, article_id=article_id)
    if title is not None:
        article.title = title
    if dek is not None:
        article.dek = dek
    if body is not None:
        article.body = body
    if author_name is not None:
        article.author_name = author_name
    if related_course_id is not None:
        article.related_course_id = related_course_id
    if position is not None:
        article.position = position
    await session.flush()
    return article


async def publish_article(
    session: AsyncSession, *, tenant_id: uuid.UUID, article_id: uuid.UUID
) -> Article:
    article = await get_article(session, tenant_id=tenant_id, article_id=article_id)
    if not article.body.strip():
        raise ArticleError("An article needs a body before it can publish.")
    article.state = "published"
    article.published_at = datetime.now(UTC)
    article.reading_minutes = _reading_minutes(article.body)
    await session.flush()
    return article


async def unpublish_article(
    session: AsyncSession, *, tenant_id: uuid.UUID, article_id: uuid.UUID
) -> Article:
    article = await get_article(session, tenant_id=tenant_id, article_id=article_id)
    article.state = "draft"
    await session.flush()
    return article


async def resolve_cover_image_url(storage: StorageService, article: Article) -> str | None:
    if not article.cover_image_object_key:
        return None
    return await storage.get_public_url(Container.PUBLIC_MARKETING, article.cover_image_object_key)


__all__ = [
    "ALLOWED_ARTICLE_EVENT_NAMES",
    "ArticleError",
    "ArticleEventName",
    "create_article",
    "get_article",
    "get_published_article",
    "list_articles",
    "list_published_articles",
    "publish_article",
    "resolve_cover_image_url",
    "unpublish_article",
    "update_article",
]
