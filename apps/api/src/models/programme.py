"""Programmes (entry paths) — runs, steps, and participants (0047).

A programme is a scheduled instantiation of a learning path for an organisation
with participants. Each cohort is a run that owns a set of cohort_steps (the
path's steps instantiated with scheduling/status) and cohort_members (the
participants).

All three tables are tenant-scoped via RLS.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

# Matching migration 0047's Postgres enum types exactly — create_type=False
# because the migration already created them.
COHORT_STATUS_VALUES = ("planned", "active", "completed", "cancelled")
CohortStatus = Enum(*COHORT_STATUS_VALUES, name="cohort_status", create_type=False)

COHORT_STEP_STATUS_VALUES = ("pending", "scheduled", "in_progress", "done", "skipped")
CohortStepStatus = Enum(*COHORT_STEP_STATUS_VALUES, name="cohort_step_status", create_type=False)

COHORT_MEMBER_ROLE_VALUES = ("participant", "observer")
CohortMemberRole = Enum(*COHORT_MEMBER_ROLE_VALUES, name="cohort_member_role", create_type=False)


class Cohort(Base, TimestampMixin):
    """A scheduled run of a learning path (or course) for an organisation."""

    __tablename__ = "cohorts"
    __table_args__ = (
        Index("ix_cohorts_tenant_id", "tenant_id"),
        Index("ix_cohorts_learning_path_id", "learning_path_id"),
        Index("ix_cohorts_organisation_id", "organisation_id"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    learning_path_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("learning_paths.id", ondelete="RESTRICT"),
        nullable=True,
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="RESTRICT"),
        nullable=True,
    )
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_facilitator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(CohortStatus, nullable=False, server_default="planned")


class CohortStep(Base, TimestampMixin):
    """Instantiation of a learning path step within a cohort run."""

    __tablename__ = "cohort_steps"
    __table_args__ = (
        Index("ix_cohort_steps_cohort_id", "cohort_id"),
        Index("ix_cohort_steps_step_id", "step_id"),
    )

    id: Mapped[uuid.UUID] = pk()
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("cohorts.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("learning_path_steps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        CohortStepStatus, nullable=False, server_default="pending"
    )
    workshop_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workshop_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Deferred foreign key to assessment_instances (added in separate feature
    # branch). Plain nullable UUID without DB-level constraint, added when both
    # branches merge.
    assessment_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )


class CohortMember(Base, TimestampMixin):
    """A participant in a cohort run."""

    __tablename__ = "cohort_members"
    __table_args__ = (
        Index("ix_cohort_members_cohort_id", "cohort_id"),
        Index("ix_cohort_members_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cohort_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("cohorts.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    path_enrolment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("path_enrolments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        CohortMemberRole, nullable=False, server_default="participant"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = ["Cohort", "CohortMember", "CohortStep"]
