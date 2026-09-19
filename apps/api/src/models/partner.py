"""Partner portal models (2026-09-11-partner-portal-design.md §4).

assessment_licences: Licences granted to partners for running assessments.
  - One run = one instance for one client organisation, regardless of respondent count
  - template_id is deferred cross-feature FK (defined in assessment platform spec)
  - requires_ttli_review gates whether submitted reports need TTLI approval

partner_profiles: Partner organisation onboarding and credential state.
  - Linked 1:1 to organisations
  - registration_number_encrypted is field-level encrypted for health professionals
  - status ('invited'|'onboarding'|'active'|'suspended') gates portal access
  - Activation requires MFA, operator agreement acceptance, and (for health pros) registration
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class AssessmentLicence(Base, TimestampMixin):
    """Assessment licence for a partner organisation.

    One run = one instance for one client organisation.
    template_id is a deferred cross-feature FK (assessment_templates.id, created
    in assessment platform spec). It is unconstrained (nullable UUID) in this branch.
    """

    __tablename__ = "assessment_licences"
    __table_args__ = (Index("ix_assessment_licences_template_id", "template_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Deferred cross-feature FK to assessment_templates.id (assessment platform spec).
    # No database constraint yet; will be added post-Sprint-1 integration.
    template_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default=text("'active'")
    )
    runs_purchased: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    runs_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # requires_ttli_review: if true, practitioner's report must pass TTLI owner inbox
    # before release to client. TTLI can relax per partner once trusted.
    requires_ttli_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    price_per_run_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class PartnerProfile(Base, TimestampMixin):
    """Partner organisation onboarding profile and agreements.

    Linked 1:1 to organisations. status gates portal access:
      'invited' -> awaiting first login
      'onboarding' -> user in MFA/agreement setup
      'active' -> all gates cleared, portal and licences usable
      'suspended' -> TTLI-initiated revocation, portal access blocked
    """

    __tablename__ = "partner_profiles"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    # Display name for partner branding (e.g., on reports)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Partner bio/description
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    # S3 object key for partner logo
    logo_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For health professionals: professional body (e.g., HPCSA)
    professional_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For health professionals: registration number (encrypted at rest)
    registration_number_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Operator agreement metadata
    operator_agreement_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_agreement_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # User who accepted the operator agreement
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    # Status: invited | onboarding | active | suspended
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="invited", server_default=text("'invited'")
    )


__all__ = ["AssessmentLicence", "PartnerProfile"]
