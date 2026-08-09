"""Leads (02 §10): the UTM quintet, source, score, stage, and the REQ-LEAD-02
progressive-profiling fields. One row per contact per tenant — repeat
submissions from the same contact update this row rather than duplicating
it, so profiling genuinely progresses instead of scattering across rows.

Deliberately not the full CRM: deals, tasks, notes, activities, campaigns,
segments and marketing-send tables are Phase 5 (02 §10) and do not exist yet.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (Index("uq_leads_tenant_contact", "tenant_id", "contact_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )

    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    stage: Mapped[str] = mapped_column(String(32), nullable=False, server_default="new")

    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_size: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline: Mapped[str | None] = mapped_column(Text, nullable=True)

    utm_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_term: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["Lead"]
