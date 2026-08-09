"""Consent records (04 §5.1, 02 §4.8). Append-only — a consent that cannot be
evidenced did not happen, the same reasoning behind audit_events. Two-layer
enforcement, also matching audit_events: no UPDATE/DELETE grant for
app_user, plus a raising trigger for any connection that does hold it.

Exactly one of user_id / contact_id is set — the CHECK constraint in
0007 enforces it — since a consent event belongs to a registered user or an
as-yet-unregistered lead contact, never neither and never both.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, pk


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('marketing', 'analytics', 'ai_processing')",
            name="ck_consent_records_purpose",
        ),
        CheckConstraint(
            "(user_id IS NULL) <> (contact_id IS NULL)", name="ck_consent_records_one_subject"
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    granted: Mapped[bool] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["ConsentRecord"]
