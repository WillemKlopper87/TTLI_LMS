"""Campaigns, segments, templates, unsubscribe (02 §10, REQ-CRM-04).

`GET /unsubscribe/{email_send_id}` is the one genuinely public,
unauthenticated route here — the same shape `GET /verify/{token}`
already established (`TenantDep`/`SessionDep`, no `PrincipalDep`): a
real preference-centre link embedded in every sent email has to work
without the recipient being signed in.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import CryptoDep, PrincipalDep, SessionDep, SettingsDep, TenantDep
from src.core.errors import NotFound
from src.models.crm import Campaign
from src.schemas.campaigns import (
    CampaignResponse,
    CampaignsPage,
    CampaignStatsResponse,
    CreateCampaignRequest,
    CreateSegmentRequest,
    CreateTemplateRequest,
    RecordBounceRequest,
    SegmentResponse,
    SegmentsPage,
    SendCampaignResponse,
    TemplateResponse,
    TemplatesPage,
)
from src.services import campaigns as campaigns_service

router = APIRouter(tags=["crm"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


@router.post("/segments", response_model=SegmentResponse, status_code=status.HTTP_201_CREATED)
async def create_segment(
    body: CreateSegmentRequest, principal: PrincipalDep, session: SessionDep
) -> SegmentResponse:
    principal.require("campaign:manage")
    segment = await campaigns_service.create_segment(
        session, tenant_id=principal.tenant_id, name=body.name, criteria=body.criteria
    )
    return SegmentResponse(id=str(segment.id), name=segment.name, criteria=segment.criteria)


@router.get("/segments", response_model=SegmentsPage)
async def list_segments(principal: PrincipalDep, session: SessionDep) -> SegmentsPage:
    principal.require("campaign:manage")
    segments = await campaigns_service.list_segments(session, tenant_id=principal.tenant_id)
    return SegmentsPage(
        items=[SegmentResponse(id=str(s.id), name=s.name, criteria=s.criteria) for s in segments]
    )


@router.post(
    "/email-templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED
)
async def create_template(
    body: CreateTemplateRequest, principal: PrincipalDep, session: SessionDep
) -> TemplateResponse:
    principal.require("campaign:manage")
    template = await campaigns_service.create_template(
        session,
        tenant_id=principal.tenant_id,
        name=body.name,
        subject=body.subject,
        body_text=body.body_text,
    )
    return TemplateResponse(
        id=str(template.id),
        name=template.name,
        subject=template.subject,
        body_text=template.body_text,
    )


@router.get("/email-templates", response_model=TemplatesPage)
async def list_templates(principal: PrincipalDep, session: SessionDep) -> TemplatesPage:
    principal.require("campaign:manage")
    templates = await campaigns_service.list_templates(session, tenant_id=principal.tenant_id)
    return TemplatesPage(
        items=[
            TemplateResponse(id=str(t.id), name=t.name, subject=t.subject, body_text=t.body_text)
            for t in templates
        ]
    )


def _campaign_response(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=str(campaign.id),
        name=campaign.name,
        template_id=str(campaign.template_id),
        segment_id=str(campaign.segment_id),
        status=campaign.status,
        sent_at=campaign.sent_at,
    )


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CreateCampaignRequest, principal: PrincipalDep, session: SessionDep
) -> CampaignResponse:
    principal.require("campaign:manage")
    campaign = await campaigns_service.create_campaign(
        session,
        tenant_id=principal.tenant_id,
        name=body.name,
        template_id=_parse_uuid(body.template_id),
        segment_id=_parse_uuid(body.segment_id),
    )
    return _campaign_response(campaign)


@router.get("/campaigns", response_model=CampaignsPage)
async def list_campaigns(principal: PrincipalDep, session: SessionDep) -> CampaignsPage:
    principal.require("campaign:manage")
    campaigns = await campaigns_service.list_campaigns(session, tenant_id=principal.tenant_id)
    return CampaignsPage(items=[_campaign_response(c) for c in campaigns])


@router.get("/campaigns/{campaign_id}", response_model=CampaignStatsResponse)
async def get_campaign(
    campaign_id: str, principal: PrincipalDep, session: SessionDep
) -> CampaignStatsResponse:
    principal.require("campaign:manage")
    stats = await campaigns_service.get_campaign_stats(
        session, tenant_id=principal.tenant_id, campaign_id=_parse_uuid(campaign_id)
    )
    return CampaignStatsResponse(
        campaign=_campaign_response(stats.campaign),
        sent=stats.sent,
        suppressed=stats.suppressed,
        bounced=stats.bounced,
    )


@router.post("/campaigns/{campaign_id}/send", response_model=SendCampaignResponse)
async def send_campaign(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    settings: SettingsDep,
) -> SendCampaignResponse:
    principal.require("campaign:manage")
    result = await campaigns_service.send_campaign(
        session,
        crypto,
        settings,
        tenant_id=principal.tenant_id,
        campaign_id=_parse_uuid(campaign_id),
    )
    return SendCampaignResponse(
        sent=result.sent,
        suppressed=result.suppressed,
        excluded_no_consent=result.excluded_no_consent,
    )


@router.post("/email-events/bounce", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def record_bounce(
    body: RecordBounceRequest, principal: PrincipalDep, session: SessionDep
) -> None:
    """Structured the way a real ESP's signed bounce webhook would call
    it — gated on `campaign:manage` for now, since no live ESP webhook
    integration exists to authenticate a genuinely public caller (02
    §10's own scope boundary, same class as `services/meeting/teams.py`
    not making real Graph calls)."""
    principal.require("campaign:manage")
    await campaigns_service.record_bounce(
        session,
        tenant_id=principal.tenant_id,
        email_send_id=_parse_uuid(body.email_send_id),
        reason=body.reason,
    )


@router.get(
    "/unsubscribe/{email_send_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def unsubscribe(email_send_id: str, tenant: TenantDep, session: SessionDep) -> None:
    await campaigns_service.unsubscribe(session, email_send_id=_parse_uuid(email_send_id))


__all__ = ["router"]
