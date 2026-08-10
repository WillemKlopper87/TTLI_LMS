from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateSegmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    criteria: dict[str, str] = Field(default_factory=dict)


class SegmentResponse(BaseModel):
    id: str
    name: str
    criteria: dict[str, object]


class SegmentsPage(BaseModel):
    items: list[SegmentResponse]


class CreateTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=200)
    body_text: str = Field(min_length=1, max_length=10000)


class TemplateResponse(BaseModel):
    id: str
    name: str
    subject: str
    body_text: str


class TemplatesPage(BaseModel):
    items: list[TemplateResponse]


class CreateCampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template_id: str
    segment_id: str


class CampaignResponse(BaseModel):
    id: str
    name: str
    template_id: str
    segment_id: str
    status: str
    sent_at: datetime | None


class CampaignsPage(BaseModel):
    items: list[CampaignResponse]


class SendCampaignResponse(BaseModel):
    sent: int
    suppressed: int
    excluded_no_consent: int


class CampaignStatsResponse(BaseModel):
    campaign: CampaignResponse
    sent: int
    suppressed: int
    bounced: int


class RecordBounceRequest(BaseModel):
    email_send_id: str
    reason: str = Field(min_length=1, max_length=200)


__all__ = [
    "CampaignResponse",
    "CampaignStatsResponse",
    "CampaignsPage",
    "CreateCampaignRequest",
    "CreateSegmentRequest",
    "CreateTemplateRequest",
    "RecordBounceRequest",
    "SegmentResponse",
    "SegmentsPage",
    "SendCampaignResponse",
    "TemplateResponse",
    "TemplatesPage",
]
