"""Article authoring and public reading (`docs/research/resources-hub-
design.md` §2). Same split as `routers/podcasts.py` — routing, permission
checks and response construction only, business logic in
`services/articles.py`. `podcast:manage` gates every write (design doc §4
decision 1 — see `0030`'s migration docstring for why this reuses that
permission rather than adding `content:manage`). `/public/articles*` needs
no auth, `TenantDep` only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import PrincipalDep, SessionDep, StorageDep, TenantDep
from src.core.errors import NotFound
from src.models.article import Article
from src.schemas.articles import (
    ArticleCreateRequest,
    ArticleResponse,
    ArticlesPageResponse,
    ArticleUpdateRequest,
)
from src.services import articles as articles_service
from src.services.storage.base import StorageService

router = APIRouter(tags=["articles"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


async def _response(storage: StorageService, article: Article) -> ArticleResponse:
    return ArticleResponse(
        id=str(article.id),
        slug=article.slug,
        title=article.title,
        dek=article.dek,
        body=article.body,
        cover_image_url=await articles_service.resolve_cover_image_url(storage, article),
        author_name=article.author_name,
        related_course_id=str(article.related_course_id) if article.related_course_id else None,
        state=article.state,
        published_at=article.published_at.isoformat() if article.published_at else None,
        reading_minutes=article.reading_minutes,
        position=article.position,
    )


@router.get("/articles", response_model=ArticlesPageResponse)
async def list_articles(
    principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> ArticlesPageResponse:
    principal.require("podcast:manage")
    items = await articles_service.list_articles(session, tenant_id=principal.tenant_id)
    return ArticlesPageResponse(items=[await _response(storage, a) for a in items])


@router.post("/articles", response_model=ArticleResponse, status_code=status.HTTP_201_CREATED)
async def create_article(
    body: ArticleCreateRequest,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
) -> ArticleResponse:
    principal.require("podcast:manage")
    article = await articles_service.create_article(
        session,
        tenant_id=principal.tenant_id,
        title=body.title,
        slug=body.slug,
        dek=body.dek,
        body=body.body,
        author_name=body.author_name,
        related_course_id=_parse_uuid(body.related_course_id) if body.related_course_id else None,
    )
    return await _response(storage, article)


@router.get("/articles/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> ArticleResponse:
    principal.require("podcast:manage")
    article = await articles_service.get_article(
        session, tenant_id=principal.tenant_id, article_id=_parse_uuid(article_id)
    )
    return await _response(storage, article)


@router.patch("/articles/{article_id}", response_model=ArticleResponse)
async def update_article(
    article_id: str,
    body: ArticleUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
) -> ArticleResponse:
    principal.require("podcast:manage")
    article = await articles_service.update_article(
        session,
        tenant_id=principal.tenant_id,
        article_id=_parse_uuid(article_id),
        title=body.title,
        dek=body.dek,
        body=body.body,
        author_name=body.author_name,
        related_course_id=_parse_uuid(body.related_course_id) if body.related_course_id else None,
        position=body.position,
    )
    return await _response(storage, article)


@router.post("/articles/{article_id}/publish", response_model=ArticleResponse)
async def publish_article(
    article_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> ArticleResponse:
    principal.require("podcast:manage")
    article = await articles_service.publish_article(
        session, tenant_id=principal.tenant_id, article_id=_parse_uuid(article_id)
    )
    return await _response(storage, article)


@router.post("/articles/{article_id}/unpublish", response_model=ArticleResponse)
async def unpublish_article(
    article_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> ArticleResponse:
    principal.require("podcast:manage")
    article = await articles_service.unpublish_article(
        session, tenant_id=principal.tenant_id, article_id=_parse_uuid(article_id)
    )
    return await _response(storage, article)


@router.get(
    "/public/articles",
    response_model=ArticlesPageResponse,
    summary="Published articles, no auth required",
)
async def list_public_articles(
    session: SessionDep, tenant: TenantDep, storage: StorageDep
) -> ArticlesPageResponse:
    items = await articles_service.list_published_articles(session, tenant_id=tenant.id)
    return ArticlesPageResponse(items=[await _response(storage, a) for a in items])


@router.get(
    "/public/articles/{slug}",
    response_model=ArticleResponse,
    summary="A published article, no auth required",
)
async def get_public_article(
    slug: str, session: SessionDep, tenant: TenantDep, storage: StorageDep
) -> ArticleResponse:
    article = await articles_service.get_published_article(session, tenant_id=tenant.id, slug=slug)
    return await _response(storage, article)


__all__ = ["router"]
