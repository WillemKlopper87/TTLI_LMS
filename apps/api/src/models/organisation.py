"""Organisations, seats (02 §4.5, REQ-TEN-02). See 0016's migration
docstring for why seat assignment reuses `entitlements` rather than a
new join table, and why `organisation_members.relationship` is a
separate concept from the RBAC `role_assignments` table.

Extends with §4.1 (partner portal design, 2026-09-11):
  - kind enum ('standard', 'partner', 'client') for partner org types —
    'standard' is the default for every ordinary organisation; a org
    only becomes 'partner' when services/partner.py::activate_partner
    promotes it (see migration 0054's docstring for why the default is
    not 'partner')
  - parent_organisation_id for client orgs linked to their partner parent
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

RELATIONSHIP_VALUES = ("member", "manager", "admin")

# Matches migration 0054's `organisation_kind` Postgres enum type exactly
# — create_type=False because the migration already created it. Mapping
# this as a plain String let every insert through SQLAlchemy fail with
# DatatypeMismatchError ("kind" is organisation_kind, not varchar).
ORGANISATION_KIND_VALUES = ("standard", "partner", "client")
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
    # §4.1: kind enum for partner organisations ('partner' or 'client')
    kind: Mapped[str] = mapped_column(
        OrganisationKind, nullable=False, default="standard", server_default=text("'standard'")
    )
    # §4.1: parent_organisation_id for client orgs to link to their partner
    parent_organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=True,
    )


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
