"""Analyst workspace: engagement and report workflow (BACKLOG L5).

AssessmentEngagement: time-windowed access grant for an analyst to work on a specific
assessment instance. The engagement is the key access-control boundary; analysts cannot
read results without an active (unrevoked, within the time window) engagement.

Report: draft report authored by an analyst on an assessment instance, flowing through
a state machine (draft → submitted → returned/accepted/withdrawn). Reviewers (users with
report:review permission) can return reports for changes or accept them, at which point
they become immutable and can be released to the organisation's admins.

ReportAttachment: PDF/PPTX file upload for a report, virus-scanned before readable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class ReportStatus(StrEnum):
    """Report lifecycle states.

    draft: Initial state, analyst is writing and can attach files.
    submitted: Ready for review, analyst has confirmed at least one clean-scanned
              attachment or non-empty summary.
    returned: Reviewer requested changes; analyst can resubmit as a new version.
    accepted: Reviewer approved; report is now immutable, its attachments become the
             release package.
    withdrawn: Analyst cancelled; terminal state.
    """

    DRAFT = "draft"
    SUBMITTED = "submitted"
    RETURNED = "returned"
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"


class AssessmentEngagement(Base, TimestampMixin):
    """Time-windowed analyst access to an assessment instance.

    This is the core access-control boundary for the analyst workspace.
    An analyst may read assessment results and submit reports only if an
    unrevoked engagement exists for them, the current time is within
    [starts_at, ends_at), and the instance is closed.

    instance_id is a deferred cross-feature FK to assessment_platform.instances.id.
    The assessment_platform feature (built on a separate branch) provides the instances
    table. This column is added as a plain UUID without a database-level constraint;
    the constraint will be added when both branches integrate after Sprint 1 closes.
    """

    __tablename__ = "assessment_engagements"
    __table_args__ = (
        Index(
            "uq_assessment_engagements_instance_analyst_active",
            "instance_id",
            "analyst_user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # TODO: Add FK to assessment_platform.instances.id once both branches integrate
    instance_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    analyst_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)


class Report(Base, TimestampMixin):
    """Report authored by an analyst on an assessment instance.

    Flows through a state machine with exact allowed transitions defined in the
    spec (§4). Reviewers (users with report:review permission) handle review,
    return, accept, and release actions.

    instance_id is a deferred cross-feature FK to assessment_platform.instances.id,
    added as a plain UUID without a database-level constraint; will be converted to
    full FK when both branches integrate after Sprint 1 closes.

    Immutable after acceptance: no edits, no attachment deletes allowed.
    """

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # TODO: Add FK to assessment_platform.instances.id once both branches integrate
    instance_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_engagements.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ReportStatus] = mapped_column(
        # values_callable: without it, SQLAlchemy's Enum type binds a
        # Python enum member's *name* ("DRAFT") to Postgres, not its
        # *value* ("draft") — but the report_status DB type's labels are
        # the lowercase values (see migration 0051), so every insert and
        # every status filter failed with "invalid input value for enum".
        SQLEnum(
            ReportStatus,
            name="report_status",
            create_type=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=ReportStatus.DRAFT.value,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportAttachment(Base):
    """PDF/PPTX file upload for a report.

    Virus-scanned before the file is readable (same fail-closed rule as assignment
    uploads). Immutable after the report is accepted.
    """

    __tablename__ = "report_attachments"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scan_result: Mapped[str | None] = mapped_column(String(16), nullable=True)


__all__ = ["AssessmentEngagement", "Report", "ReportAttachment", "ReportStatus"]
