"""Analyst workspace: engagement, access policy, and report state machine (BACKLOG L5).

The analyst workspace controls analyst access to assessment results through time-
windowed engagements and flows reports through a strict state machine. This service
implements the core logic:

1. Engagement assignment and revocation (admin-only actions)
2. Access policy: engagement must be active (unrevoked, within time window)
3. Report state machine transitions (§4 of the spec)
4. Audit events for analyst reads (including row count)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, Forbidden, NotFound
from src.models.analyst import AssessmentEngagement, Report, ReportAttachment, ReportStatus
from src.models.audit import AuditAction
from src.services import audit

log = structlog.get_logger()


class EngagementNotFound(NotFound):
    """Engagement does not exist or is not accessible to the current user."""

    code = "ENGAGEMENT_NOT_FOUND"


class EngagementExpired(Forbidden):
    """Engagement is outside its time window."""

    code = "ENGAGEMENT_EXPIRED"


class EngagementRevoked(Forbidden):
    """Engagement has been revoked by an admin."""

    code = "ENGAGEMENT_REVOKED"


class InstanceNotClosed(AppError):
    """Instance is not in closed status; analyst cannot read results."""

    status_code = 409
    code = "INSTANCE_NOT_CLOSED"


class ReportNotFound(NotFound):
    """Report does not exist or is not accessible."""

    code = "REPORT_NOT_FOUND"


class ReportAlreadyExists(AppError):
    """One open draft report already exists for this engagement."""

    code = "REPORT_ALREADY_EXISTS"


class InvalidReportTransition(AppError):
    """Requested state transition is not allowed by the state machine."""

    code = "INVALID_REPORT_TRANSITION"


class ReportImmutable(AppError):
    """Report is accepted and cannot be modified."""

    code = "REPORT_IMMUTABLE"


async def assign_engagement(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    analyst_user_id: uuid.UUID,
    instance_id: uuid.UUID,
    assigned_by: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    purpose: str,
) -> AssessmentEngagement:
    """Assign an analyst to an assessment instance (admin-only).

    The partial unique index (instance_id, analyst_user_id) WHERE revoked_at IS NULL
    enforces only one active engagement per analyst/instance pair. Creating a new
    engagement when an active one exists will violate the unique constraint.
    """
    engagement = AssessmentEngagement(
        tenant_id=tenant_id,
        instance_id=instance_id,
        analyst_user_id=analyst_user_id,
        assigned_by=assigned_by,
        starts_at=starts_at,
        ends_at=ends_at,
        purpose=purpose,
    )
    session.add(engagement)
    await session.flush()
    return engagement


async def revoke_engagement(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    engagement_id: uuid.UUID,
) -> AssessmentEngagement:
    """Revoke an engagement, immediately terminating the analyst's access.

    Raises EngagementNotFound if the engagement does not belong to the tenant.
    """
    stmt = select(AssessmentEngagement).where(
        AssessmentEngagement.id == engagement_id,
        AssessmentEngagement.tenant_id == tenant_id,
    )
    engagement = (await session.execute(stmt)).scalar_one_or_none()
    if engagement is None:
        raise EngagementNotFound("Engagement not found.")

    engagement.revoked_at = datetime.now(UTC)
    await session.flush()
    return engagement


async def check_engagement_access(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    analyst_user_id: uuid.UUID,
    instance_id: uuid.UUID,
) -> AssessmentEngagement:
    """Verify the analyst has active access to the instance via an engagement.

    Returns the engagement if valid. Raises:
    - EngagementNotFound: No engagement exists
    - EngagementRevoked: Engagement has been revoked
    - EngagementExpired: Current time is outside [starts_at, ends_at)
    - InstanceNotClosed: Instance is not closed (stub until assessment-platform integrates)

    NOTE: The instance-closed check is stubbed and always passes because the instances
    table does not yet exist in this branch (cross-feature FK with assessment-platform).
    """
    now = datetime.now(UTC)

    stmt = select(AssessmentEngagement).where(
        AssessmentEngagement.tenant_id == tenant_id,
        AssessmentEngagement.analyst_user_id == analyst_user_id,
        AssessmentEngagement.instance_id == instance_id,
    )
    engagement = (await session.execute(stmt)).scalar_one_or_none()

    if engagement is None:
        raise EngagementNotFound("No engagement found for this analyst/instance pair.")

    if engagement.revoked_at is not None:
        raise EngagementRevoked("This engagement has been revoked.")

    if not (engagement.starts_at <= now < engagement.ends_at):
        raise EngagementExpired("This engagement is outside its valid time window.")

    # TODO: Uncomment once assessment_platform.instances exists in the database
    # if engagement.instance.status != "closed":
    #     raise InstanceNotClosed("The instance is not closed yet.")

    return engagement


async def record_analyst_read(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    analyst_user_id: uuid.UUID,
    entity_type: str,  # e.g., "assessment_results" or "assessment_export"
    row_count: int,
) -> None:
    """Record an audit event for an analyst's read of assessment data.

    Every analyst read (results, export) is audited with the row count, per the spec.
    """
    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.ANALYST_DATA_READ,
        actor_user_id=analyst_user_id,
        entity_type=entity_type,
        after={"row_count": row_count},
    )


async def create_report_draft(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    engagement_id: uuid.UUID,
    author_user_id: uuid.UUID,
    title: str,
) -> Report:
    """Create a new draft report for an engagement.

    Enforces one open draft per engagement (checked by the state machine constraint).
    The engagement_id FK ensures the report belongs to a valid engagement for the tenant.

    Raises ReportAlreadyExists if a draft already exists for this engagement.
    """
    # Check if a draft already exists for this engagement
    stmt = select(Report).where(
        Report.engagement_id == engagement_id,
        Report.status == ReportStatus.DRAFT,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise ReportAlreadyExists("A draft report already exists for this engagement.")

    # Get engagement to extract instance_id and verify tenant isolation
    engagement_stmt = select(AssessmentEngagement).where(
        AssessmentEngagement.id == engagement_id,
        AssessmentEngagement.tenant_id == tenant_id,
    )
    engagement = (await session.execute(engagement_stmt)).scalar_one_or_none()
    if engagement is None:
        raise NotFound("Engagement not found.")

    report = Report(
        tenant_id=tenant_id,
        instance_id=engagement.instance_id,
        engagement_id=engagement_id,
        author_user_id=author_user_id,
        title=title,
        status=ReportStatus.DRAFT,
    )
    session.add(report)
    await session.flush()
    return report


async def submit_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
    author_user_id: uuid.UUID,
) -> Report:
    """Transition a report from draft to submitted.

    Requires at least one clean-scanned attachment OR non-empty summary.
    Author-only action. Raises InvalidReportTransition if conditions not met.
    """
    stmt = select(Report).where(
        Report.id == report_id,
        Report.tenant_id == tenant_id,
        Report.author_user_id == author_user_id,
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise ReportNotFound("Report not found or you are not the author.")

    if report.status != ReportStatus.DRAFT:
        raise InvalidReportTransition(
            f"Cannot submit from {report.status.value} status. "
            f"Submit is only allowed from draft."
        )

    # Check: at least one clean attachment or non-empty summary
    has_summary = report.summary and report.summary.strip()

    attachments_stmt = select(ReportAttachment).where(
        ReportAttachment.report_id == report_id,
        ReportAttachment.scan_result == "clean",
    )
    clean_attachments = (await session.execute(attachments_stmt)).scalars().all()
    has_clean_attachment = len(clean_attachments) > 0

    if not (has_summary or has_clean_attachment):
        raise InvalidReportTransition(
            "Cannot submit: report must have a non-empty summary or at least one clean attachment."
        )

    report.status = ReportStatus.SUBMITTED
    report.submitted_at = datetime.now(UTC)
    await session.flush()
    return report


async def return_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    decision_note: str,
) -> Report:
    """Transition a report from submitted to returned.

    Reviewer-only action (report:review permission). Requires a decision_note.
    Analyst can then resubmit as a new version.
    """
    stmt = select(Report).where(
        Report.id == report_id,
        Report.tenant_id == tenant_id,
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise ReportNotFound("Report not found.")

    if report.status != ReportStatus.SUBMITTED:
        raise InvalidReportTransition(
            f"Cannot return from {report.status.value} status. "
            f"Return is only allowed from submitted."
        )

    if not decision_note or not decision_note.strip():
        raise AppError("decision_note is required.")

    report.status = ReportStatus.RETURNED
    report.decided_at = datetime.now(UTC)
    report.decided_by = reviewer_user_id
    report.decision_note = decision_note
    await session.flush()
    return report


async def resubmit_returned_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
    author_user_id: uuid.UUID,
) -> Report:
    """Transition a returned report back to submitted, creating a new version.

    Previous attachments are kept. Version is incremented. Author-only.
    Enforces the same submission requirements as initial submit.
    """
    stmt = select(Report).where(
        Report.id == report_id,
        Report.tenant_id == tenant_id,
        Report.author_user_id == author_user_id,
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise ReportNotFound("Report not found or you are not the author.")

    if report.status != ReportStatus.RETURNED:
        raise InvalidReportTransition(
            f"Cannot resubmit from {report.status.value} status. "
            f"Resubmit is only allowed from returned."
        )

    # Check: at least one clean attachment or non-empty summary
    has_summary = report.summary and report.summary.strip()

    attachments_stmt = select(ReportAttachment).where(
        ReportAttachment.report_id == report_id,
        ReportAttachment.scan_result == "clean",
    )
    clean_attachments = (await session.execute(attachments_stmt)).scalars().all()
    has_clean_attachment = len(clean_attachments) > 0

    if not (has_summary or has_clean_attachment):
        raise InvalidReportTransition(
            "Cannot resubmit: report must have a summary or clean attachment."
        )

    report.status = ReportStatus.SUBMITTED
    report.submitted_at = datetime.now(UTC)
    report.version += 1
    await session.flush()
    return report


async def accept_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
) -> Report:
    """Transition a report from submitted to accepted (immutable).

    Reviewer-only action. After acceptance, no edits or attachment deletes are allowed.
    """
    stmt = select(Report).where(
        Report.id == report_id,
        Report.tenant_id == tenant_id,
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise ReportNotFound("Report not found.")

    if report.status != ReportStatus.SUBMITTED:
        raise InvalidReportTransition(
            f"Cannot accept from {report.status.value} status. "
            f"Accept is only allowed from submitted."
        )

    report.status = ReportStatus.ACCEPTED
    report.decided_at = datetime.now(UTC)
    report.decided_by = reviewer_user_id
    await session.flush()
    return report


async def withdraw_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
    author_user_id: uuid.UUID,
) -> Report:
    """Transition a report from draft or returned to withdrawn (terminal).

    Author-only action. Withdrawal is final; no further editing.
    """
    stmt = select(Report).where(
        Report.id == report_id,
        Report.tenant_id == tenant_id,
        Report.author_user_id == author_user_id,
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise ReportNotFound("Report not found or you are not the author.")

    if report.status not in (ReportStatus.DRAFT, ReportStatus.RETURNED):
        raise InvalidReportTransition(
            f"Cannot withdraw from {report.status.value} status. "
            f"Withdrawal is only allowed from draft or returned."
        )

    report.status = ReportStatus.WITHDRAWN
    await session.flush()
    return report


async def release_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
) -> Report:
    """Mark an accepted report as released to the organisation.

    Reviewer-only action. Released reports become visible to organisation admins
    in the "Assessments" tab. This is a separate, explicit step from acceptance.
    """
    stmt = select(Report).where(
        Report.id == report_id,
        Report.tenant_id == tenant_id,
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise ReportNotFound("Report not found.")

    if report.status != ReportStatus.ACCEPTED:
        raise InvalidReportTransition(
            f"Can only release accepted reports, not {report.status.value}."
        )

    report.released_at = datetime.now(UTC)
    await session.flush()
    return report


async def get_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
) -> Report:
    """Fetch a report by ID with tenant isolation."""
    stmt = select(Report).where(
        Report.id == report_id,
        Report.tenant_id == tenant_id,
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if report is None:
        raise ReportNotFound("Report not found.")
    return report


__all__ = [
    "AssessmentEngagement",
    "Report",
    "ReportAttachment",
    "ReportStatus",
    "accept_report",
    "assign_engagement",
    "check_engagement_access",
    "create_report_draft",
    "get_report",
    "record_analyst_read",
    "release_report",
    "resubmit_returned_report",
    "return_report",
    "revoke_engagement",
    "submit_report",
    "withdraw_report",
]
