"""Organisations, seats (02 §4.5, REQ-TEN-02). See 0016's migration
docstring for why seat assignment reuses `entitlements` rather than a
new join table, and why `organisation_members.relationship` is a
separate concept from the RBAC `role_assignments` table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

RELATIONSHIP_VALUES = ("member", "manager", "admin")


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
