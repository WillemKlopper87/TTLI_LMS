"""Request and response schemas for the analyst workspace (BACKLOG L5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# --- Engagement assignment (admin-only) ---


class AssignEngagementRequest(BaseModel):
    """Admin assigns an analyst to an assessment instance."""

    analyst_user_id: UUID
    instance_id: UUID
    starts_at: datetime
    ends_at: datetime
    purpose: str = Field(min_length=1, max_length=500)


class EngagementView(BaseModel):
    """An analyst's engagement on an assessment instance."""

    id: UUID
    instance_id: UUID | None
    analyst_user_id: UUID
    starts_at: datetime
    ends_at: datetime
    revoked_at: datetime | None = None
    purpose: str
    created_at: datetime


class RevokeEngagementRequest(BaseModel):
    """Admin revokes an engagement."""

    pass  # No body needed; ID is in URL


# --- Report workflow ---


class CreateReportRequest(BaseModel):
    """Analyst creates a draft report."""

    engagement_id: UUID
    title: str = Field(min_length=1, max_length=500)


class ReportView(BaseModel):
    """A report at any stage in its lifecycle."""

    id: UUID
    engagement_id: UUID
    instance_id: UUID | None
    author_user_id: UUID
    status: str  # "draft", "submitted", "returned", "accepted", "withdrawn"
    title: str
    summary: str | None = None
    version: int
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    decision_note: str | None = None
    released_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UpdateReportSummaryRequest(BaseModel):
    """Analyst sets a report's summary. Author-only, draft/returned only."""

    summary: str = Field(min_length=1, max_length=20000)


class SubmitReportRequest(BaseModel):
    """Analyst submits a draft report for review."""

    pass  # No body needed; ID is in URL


class ReturnReportRequest(BaseModel):
    """Reviewer returns a report to the analyst."""

    decision_note: str = Field(min_length=1)


class ResubmitReportRequest(BaseModel):
    """Analyst resubmits a returned report as a new version."""

    pass  # No body needed; ID is in URL


class AcceptReportRequest(BaseModel):
    """Reviewer accepts a report (makes it immutable)."""

    pass  # No body needed; ID is in URL


class WithdrawReportRequest(BaseModel):
    """Analyst withdraws a draft or returned report."""

    pass  # No body needed; ID is in URL


class ReleaseReportRequest(BaseModel):
    """Reviewer releases an accepted report to the organisation."""

    pass  # No body needed; ID is in URL


class ReportAttachmentView(BaseModel):
    """Metadata for a report attachment."""

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    scanned_at: datetime | None = None
    scan_result: str | None = None


class ReportWithAttachmentsView(ReportView):
    """A report with its attachments."""

    attachments: list[ReportAttachmentView] = Field(default_factory=list)


class EngagementsPageResponse(BaseModel):
    """A list of engagements."""

    items: list[EngagementView]


class ReportsPageResponse(BaseModel):
    """A list of reports."""

    items: list[ReportView]


__all__ = [
    "AcceptReportRequest",
    "AssignEngagementRequest",
    "CreateReportRequest",
    "EngagementView",
    "EngagementsPageResponse",
    "ReleaseReportRequest",
    "ReportAttachmentView",
    "ReportView",
    "ReportWithAttachmentsView",
    "ReportsPageResponse",
    "ResubmitReportRequest",
    "ReturnReportRequest",
    "RevokeEngagementRequest",
    "SubmitReportRequest",
    "UpdateReportSummaryRequest",
    "WithdrawReportRequest",
]
