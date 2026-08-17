"""Recommendation authoring and public reading (`docs/research/resources-
hub-design.md` §3). Same split as `routers/articles.py` — routing,
permission checks and response construction only. `podcast:manage` gates
every write; `/public/recommendations` needs no auth, `TenantDep` only.
No detail route — the design doc's own §3.1: a recommendation links out,
it doesn't host a page.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import PrincipalDep, SessionDep, TenantDep
from src.core.errors import NotFound
from src.models.recommendation import Recommendation
from src.schemas.recommendations import (
    RecommendationCreateRequest,
    RecommendationResponse,
    RecommendationsPageResponse,
    RecommendationUpdateRequest,
)
from src.services import recommendations as recommendations_service

router = APIRouter(tags=["recommendations"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


def _response(recommendation: Recommendation) -> RecommendationResponse:
    return RecommendationResponse(
        id=str(recommendation.id),
        title=recommendation.title,
        url=recommendation.url,
        source_name=recommendation.source_name,
        curator_name=recommendation.curator_name,
        curator_note=recommendation.curator_note,
        related_course_id=(
            str(recommendation.related_course_id) if recommendation.related_course_id else None
        ),
        state=recommendation.state,
        position=recommendation.position,
    )


@router.get("/recommendations", response_model=RecommendationsPageResponse)
async def list_recommendations(
    principal: PrincipalDep, session: SessionDep
) -> RecommendationsPageResponse:
    principal.require("podcast:manage")
    items = await recommendations_service.list_recommendations(
        session, tenant_id=principal.tenant_id
    )
    return RecommendationsPageResponse(items=[_response(r) for r in items])


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_recommendation(
    body: RecommendationCreateRequest, principal: PrincipalDep, session: SessionDep
) -> RecommendationResponse:
    principal.require("podcast:manage")
    recommendation = await recommendations_service.create_recommendation(
        session,
        tenant_id=principal.tenant_id,
        title=body.title,
        url=body.url,
        source_name=body.source_name,
        curator_name=body.curator_name,
        curator_note=body.curator_note,
        related_course_id=_parse_uuid(body.related_course_id) if body.related_course_id else None,
    )
    return _response(recommendation)


@router.get("/recommendations/{recommendation_id}", response_model=RecommendationResponse)
async def get_recommendation(
    recommendation_id: str, principal: PrincipalDep, session: SessionDep
) -> RecommendationResponse:
    principal.require("podcast:manage")
    recommendation = await recommendations_service.get_recommendation(
        session, tenant_id=principal.tenant_id, recommendation_id=_parse_uuid(recommendation_id)
    )
    return _response(recommendation)


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationResponse)
async def update_recommendation(
    recommendation_id: str,
    body: RecommendationUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> RecommendationResponse:
    principal.require("podcast:manage")
    recommendation = await recommendations_service.update_recommendation(
        session,
        tenant_id=principal.tenant_id,
        recommendation_id=_parse_uuid(recommendation_id),
        title=body.title,
        url=body.url,
        source_name=body.source_name,
        curator_name=body.curator_name,
        curator_note=body.curator_note,
        related_course_id=_parse_uuid(body.related_course_id) if body.related_course_id else None,
        position=body.position,
    )
    return _response(recommendation)


@router.post("/recommendations/{recommendation_id}/publish", response_model=RecommendationResponse)
async def publish_recommendation(
    recommendation_id: str, principal: PrincipalDep, session: SessionDep
) -> RecommendationResponse:
    principal.require("podcast:manage")
    recommendation = await recommendations_service.publish_recommendation(
        session, tenant_id=principal.tenant_id, recommendation_id=_parse_uuid(recommendation_id)
    )
    return _response(recommendation)


@router.post(
    "/recommendations/{recommendation_id}/unpublish", response_model=RecommendationResponse
)
async def unpublish_recommendation(
    recommendation_id: str, principal: PrincipalDep, session: SessionDep
) -> RecommendationResponse:
    principal.require("podcast:manage")
    recommendation = await recommendations_service.unpublish_recommendation(
        session, tenant_id=principal.tenant_id, recommendation_id=_parse_uuid(recommendation_id)
    )
    return _response(recommendation)


@router.get(
    "/public/recommendations",
    response_model=RecommendationsPageResponse,
    summary="Published recommendations, no auth required",
)
async def list_public_recommendations(
    session: SessionDep, tenant: TenantDep
) -> RecommendationsPageResponse:
    items = await recommendations_service.list_published_recommendations(
        session, tenant_id=tenant.id
    )
    return RecommendationsPageResponse(items=[_response(r) for r in items])


__all__ = ["router"]
