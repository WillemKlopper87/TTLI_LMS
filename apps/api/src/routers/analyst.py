"""Analyst workspace: engagement and report workflow (BACKLOG L5).

Core endpoints for the first slice:
- Assignment: POST /assessments/engagements (admin assigns)
- Revocation: POST /assessments/engagements/{id}/revoke (admin revokes)
- Report CRUD: POST /reports, GET /reports/{id}
- Report state machine: POST /reports/{id}/submit | /return | /accept | /withdraw | /release

Not in this slice: results/export endpoints (GET /analyst/engagements/{id}/results,
GET /analyst/engagements/{id}/export.(csv|json)) because they need the real instances
table, and results retrieval is the assessment-platform responsibility.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import AuditedSessionDep, PrincipalDep, SessionDep
from src.schemas.analyst import (
    AcceptReportRequest,
    AssignEngagementRequest,
    CreateReportRequest,
    EngagementView,
    ReleaseReportRequest,
    ReportView,
    ResubmitReportRequest,
    ReturnReportRequest,
    RevokeEngagementRequest,
    SubmitReportRequest,
    WithdrawReportRequest,
)
from src.services import analyst

router = APIRouter(tags=["analyst"])

# Permissions (per spec §3 and 4)
ASSESSMENT_RUN = "assessment:run"  # Admin action: assign/revoke engagements
ASSESSMENT_ANALYSE = "assessment:analyse"  # Analyst role: read results
REPORT_SUBMIT = "report:submit"  # Analyst: create/edit reports
REPORT_REVIEW = "report:review"  # Owner/reviewer: review, return, accept, release


@router.post(
    "/assessments/engagements",
    response_model=EngagementView,
    status_code=status.HTTP_201_CREATED,
    summary="Assign an analyst to an assessment instance (admin-only)",
)
async def assign_engagement(
    body: AssignEngagementRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> EngagementView:
    """Admin assigns an analyst to an assessment instance with a time window.

    The partial unique index ensures only one active engagement per analyst/instance.
    If an engagement already exists, this will fail with a unique constraint violation.
    """
    principal.require(ASSESSMENT_RUN)

    engagement = await analyst.assign_engagement(
        session,
        tenant_id=principal.tenant_id,
        analyst_user_id=body.analyst_user_id,
        instance_id=body.instance_id,
        assigned_by=principal.user_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        purpose=body.purpose,
    )

    return EngagementView(
        id=engagement.id,
        instance_id=engagement.instance_id,
        analyst_user_id=engagement.analyst_user_id,
        starts_at=engagement.starts_at,
        ends_at=engagement.ends_at,
        revoked_at=engagement.revoked_at,
        purpose=engagement.purpose,
        created_at=engagement.created_at,
    )


@router.post(
    "/assessments/engagements/{engagement_id}/revoke",
    response_model=EngagementView,
    summary="Revoke an engagement (admin-only)",
)
async def revoke_engagement(
    engagement_id: uuid.UUID,
    body: RevokeEngagementRequest,  # Empty body, just for OpenAPI
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> EngagementView:
    """Admin revokes an engagement, immediately terminating the analyst's access."""
    principal.require(ASSESSMENT_RUN)

    engagement = await analyst.revoke_engagement(
        session,
        tenant_id=principal.tenant_id,
        engagement_id=engagement_id,
    )

    return EngagementView(
        id=engagement.id,
        instance_id=engagement.instance_id,
        analyst_user_id=engagement.analyst_user_id,
        starts_at=engagement.starts_at,
        ends_at=engagement.ends_at,
        revoked_at=engagement.revoked_at,
        purpose=engagement.purpose,
        created_at=engagement.created_at,
    )


@router.post(
    "/reports",
    response_model=ReportView,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft report on an assessment",
)
async def create_report(
    body: CreateReportRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ReportView:
    """Analyst creates a draft report for an engagement.

    One open draft per engagement is enforced. Returns 409 if a draft already exists.
    """
    principal.require(REPORT_SUBMIT)

    report = await analyst.create_report_draft(
        session,
        tenant_id=principal.tenant_id,
        engagement_id=body.engagement_id,
        author_user_id=principal.user_id,
        title=body.title,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.get(
    "/reports/{report_id}",
    response_model=ReportView,
    summary="Fetch a report by ID",
)
async def get_report(
    report_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> ReportView:
    """Fetch a report for reading.

    Analyst can read their own reports; reviewers can read any report.
    (Permission checks simplified for first slice; full implementation adds role-based visibility.)
    """
    report = await analyst.get_report(
        session,
        tenant_id=principal.tenant_id,
        report_id=report_id,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "/reports/{report_id}/submit",
    response_model=ReportView,
    summary="Submit a draft report for review",
)
async def submit_report(
    report_id: uuid.UUID,
    body: SubmitReportRequest,  # Empty body
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ReportView:
    """Analyst submits a draft report for review.

    Requires at least one clean-scanned attachment or non-empty summary.
    Author-only action.
    """
    principal.require(REPORT_SUBMIT)

    report = await analyst.submit_report(
        session,
        tenant_id=principal.tenant_id,
        report_id=report_id,
        author_user_id=principal.user_id,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "/reports/{report_id}/return",
    response_model=ReportView,
    summary="Return a report to the analyst for revision",
)
async def return_report(
    report_id: uuid.UUID,
    body: ReturnReportRequest,
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ReportView:
    """Reviewer returns a submitted report to the analyst.

    Analyst can then resubmit as a new version. Requires a decision_note.
    Reviewer-only action (report:review permission).
    """
    principal.require(REPORT_REVIEW)

    report = await analyst.return_report(
        session,
        tenant_id=principal.tenant_id,
        report_id=report_id,
        reviewer_user_id=principal.user_id,
        decision_note=body.decision_note,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "/reports/{report_id}/resubmit",
    response_model=ReportView,
    summary="Resubmit a returned report as a new version",
)
async def resubmit_report(
    report_id: uuid.UUID,
    body: ResubmitReportRequest,  # Empty body
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ReportView:
    """Analyst resubmits a returned report as a new version.

    Previous attachments are kept. Version is incremented.
    Author-only action. Same submission requirements as initial submit.
    """
    principal.require(REPORT_SUBMIT)

    report = await analyst.resubmit_returned_report(
        session,
        tenant_id=principal.tenant_id,
        report_id=report_id,
        author_user_id=principal.user_id,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "/reports/{report_id}/accept",
    response_model=ReportView,
    summary="Accept a report (makes it immutable)",
)
async def accept_report(
    report_id: uuid.UUID,
    body: AcceptReportRequest,  # Empty body
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ReportView:
    """Reviewer accepts a submitted report.

    Report becomes immutable. Attachments become the release package.
    Reviewer-only action (report:review permission).
    """
    principal.require(REPORT_REVIEW)

    report = await analyst.accept_report(
        session,
        tenant_id=principal.tenant_id,
        report_id=report_id,
        reviewer_user_id=principal.user_id,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "/reports/{report_id}/withdraw",
    response_model=ReportView,
    summary="Withdraw a report (terminal)",
)
async def withdraw_report(
    report_id: uuid.UUID,
    body: WithdrawReportRequest,  # Empty body
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ReportView:
    """Analyst withdraws a draft or returned report.

    Withdrawal is terminal; no further editing. Author-only action.
    """
    principal.require(REPORT_SUBMIT)

    report = await analyst.withdraw_report(
        session,
        tenant_id=principal.tenant_id,
        report_id=report_id,
        author_user_id=principal.user_id,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "/reports/{report_id}/release",
    response_model=ReportView,
    summary="Release an accepted report to the organisation",
)
async def release_report(
    report_id: uuid.UUID,
    body: ReleaseReportRequest,  # Empty body
    principal: PrincipalDep,
    session: AuditedSessionDep,
) -> ReportView:
    """Reviewer releases an accepted report to the organisation.

    Released reports become visible to organisation admins in the "Assessments" tab.
    Reviewer-only action (report:review permission).
    """
    principal.require(REPORT_REVIEW)

    report = await analyst.release_report(
        session,
        tenant_id=principal.tenant_id,
        report_id=report_id,
        reviewer_user_id=principal.user_id,
    )

    return ReportView(
        id=report.id,
        engagement_id=report.engagement_id,
        instance_id=report.instance_id,
        author_user_id=report.author_user_id,
        status=report.status.value,
        title=report.title,
        summary=report.summary,
        version=report.version,
        submitted_at=report.submitted_at,
        decided_at=report.decided_at,
        decided_by=report.decided_by,
        decision_note=report.decision_note,
        released_at=report.released_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


__all__ = ["router"]
