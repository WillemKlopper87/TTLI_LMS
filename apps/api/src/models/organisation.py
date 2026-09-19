"""Organisations, seats (02 §4.5, REQ-TEN-02). See 0016's migration
docstring for why seat assignment reuses `entitlements` rather than a
new join table, and why `organisation_members.relationship` is a
separate concept from the RBAC `role_assignments` table.

Two features extend this table with `kind` (a single column, so a single
enum — reconciled when partner portal and facilitator licensing were
integrated):
  - partner portal (§4.1, 2026-09-11): 'standard' (default, every ordinary
    organisation), 'partner' (promoted by services/partner.py::
    activate_partner) and 'client' (linked to a partner parent via
    `parent_organisation_id`). See migration 0054 for why the default is
    'standard', not 'partner'.
  - facilitator licensing (2026-09-11-facilitator-licensing-xapi-design.md
    §3): 'licensee' — an organisation TTLI has granted facilitator
    licences to. services/licence.py::create_licence requires it. Added to
    the enum by migration 0055, which also adds `logo_object_key`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

RELATIONSHIP_VALUES = ("member", "manager", "admin")

# Matches the `organisation_kind` Postgres enum type exactly — created by
# migration 0054 and extended with 'licensee' by 0055; create_type=False
# because the migrations own it. Mapping this as a plain String let every
# insert through SQLAlchemy fail with DatatypeMismatchError ("kind" is
# organisation_kind, not varchar).
ORGANISATION_KIND_VALUES = ("standard", "partner", "client", "licensee")
OrganisationKind = Enum(*ORGANISATION_KIND_VALUES, name="organisation_kind", create_type=False)


class Organisation(Base, TimestampMixin):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vat_number_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    billing_address_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'standard' (default), 'partner', 'client' (partner portal, migration
    # 0054) or 'licensee' (facilitator licensing, migration 0055).
    kind: Mapped[str] = mapped_column(
        OrganisationKind, nullable=False, default="standard", server_default=text("'standard'")
    )
    # Client organisations link to their partner parent (partner portal §4.1).
    parent_organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # A licensee's branding on licensed content (facilitator licensing,
    # migration 0055).
    logo_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrganisationMember(Base):
    __tablename__ = "organisation_members"
    __table_args__ = (
        Index("uq_organisation_members_org_user", "organisation_id", "user_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = ["RELATIONSHIP_VALUES", "Organisation", "OrganisationMember"]
