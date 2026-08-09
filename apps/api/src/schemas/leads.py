from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LeadRequest(BaseModel):
    # REQ-LEAD-01 minimum fields.
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    privacy_consent: bool
    marketing_consent: bool = False

    # REQ-LEAD-03: the UTM quintet.
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None

    # REQ-LEAD-02: progressive profiling. All optional — a first submission
    # may carry none of these; a later one fills in more.
    company: str | None = None
    job_title: str | None = None
    industry: str | None = None
    team_size: str | None = None
    training_goal: str | None = None
    budget: str | None = None
    timeline: str | None = None

    # The contact form's free-text message — not really "progressive
    # profiling" in spirit, but stored the same way (services/leads.py).
    message: str | None = Field(default=None, max_length=4000)

    source: str | None = None


class LeadSummary(BaseModel):
    lead_id: str
    contact_id: str
    email: str
    first_name: str | None
    last_name: str | None
    company: str | None
    job_title: str | None
    message: str | None
    source: str | None
    score: int
    stage: str
    created_at: datetime


class LeadsPage(BaseModel):
    items: list[LeadSummary]
    total: int
    limit: int
    offset: int


__all__ = ["LeadRequest", "LeadSummary", "LeadsPage"]
