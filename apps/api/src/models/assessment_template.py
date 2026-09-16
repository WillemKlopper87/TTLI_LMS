"""Assessment platform: sellable B2B assessment templates and instances
(§2026-09-11-assessment-platform-design.md §3).

Extends the survey subsystem as a standalone, sellable form. Templates are
tenant-owned product definitions versioned by slug; instances are runs for one
organisation carrying a snapshot of the template's questions (editable in draft,
frozen on open). Subjects are the people being assessed. Invitations carry invite
tokens and respondent metadata. Responses are anonymous or identified answers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class AssessmentTemplate(Base, TimestampMixin):
    """Tenant-owned product definition: the template for an assessment."""

    __tablename__ = "assessment_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", "version", name="uq_templates_tenant_slug_version"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'org_survey'")
    )
    rater_groups: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, server_default=text("'[]'::jsonb")
    )
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'identified'")
    )
    minimum_group_size: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    price_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class AssessmentTemplateQuestion(Base):
    """Frozen per template version; copied from question bank on creation."""

    __tablename__ = "assessment_template_questions"

    id: Mapped[uuid.UUID] = pk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AssessmentInstance(Base, TimestampMixin):
    """One run for one organisation, carrying a snapshot of the template."""

    __tablename__ = "assessment_instances"
    __table_args__ = (
        CheckConstraint(
            "(evaluation_role = 'standalone' AND pair_id IS NULL) OR "
            "(evaluation_role IN ('pre', 'post') AND pair_id IS NOT NULL)",
            name="ck_assessment_instances_evaluation_pair",
        ),
        Index(
            "uq_assessment_instances_pair_pre",
            "pair_id",
            unique=True,
            postgresql_where=text("evaluation_role = 'pre'"),
        ),
        Index(
            "uq_assessment_instances_pair_post",
            "pair_id",
            unique=True,
            postgresql_where=text("evaluation_role = 'post'"),
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    evaluation_role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'standalone'")
    )
    pair_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    levels_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    question_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class AssessmentSubject(Base, TimestampMixin):
    """The person being assessed (multi_rater, individual, external_instrument only)."""

    __tablename__ = "assessment_subjects"

    id: Mapped[uuid.UUID] = pk()
    instance_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    email_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )


class AssessmentInvitation(Base):
    """Invite token and respondent metadata (may be anonymous)."""

    __tablename__ = "assessment_invitations"

    id: Mapped[uuid.UUID] = pk()
    instance_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_subjects.id", ondelete="CASCADE"),
        nullable=True,
    )
    rater_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    email_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentResponse(Base):
    """Response (answer set) from a respondent, anonymous or identified.

    user_id and respondent_reference are mutually exclusive — an anonymous
    response never carries anything that identifies who submitted it.
    """

    __tablename__ = "assessment_responses"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) <> (respondent_reference IS NULL)",
            name="ck_assessment_responses_one_subject",
        ),
        UniqueConstraint("instance_id", "invitation_id", name="uq_responses_instance_invitation"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_instances.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    rater_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    respondent_reference: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    answers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class AssessmentSubjectResult(Base, TimestampMixin):
    """External instrument results: practitioner report and scores."""

    __tablename__ = "assessment_subject_results"

    id: Mapped[uuid.UUID] = pk()
    subject_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    administered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    administered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vendor_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    report_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)


__all__ = [
    "AssessmentInstance",
    "AssessmentInvitation",
    "AssessmentResponse",
    "AssessmentSubject",
    "AssessmentSubjectResult",
    "AssessmentTemplate",
    "AssessmentTemplateQuestion",
]
