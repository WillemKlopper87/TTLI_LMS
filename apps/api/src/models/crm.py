"""CRM and marketing engine (02 §10, REQ-CRM-01 through REQ-CRM-05).
See `0019`'s migration docstring for the deal-centric shape and what
this sprint deliberately deferred.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

DEAL_STAGE_VALUES = ("new", "qualified", "proposal", "won", "lost")
CAMPAIGN_STATUS_VALUES = ("draft", "sending", "sent")
EMAIL_SEND_STATUS_VALUES = ("queued", "sent", "failed", "suppressed", "bounced")

# create_type=False: 0019 creates these Postgres enum types explicitly.
DealStage = Enum(*DEAL_STAGE_VALUES, name="deal_stage", create_type=False)
CampaignStatus = Enum(*CAMPAIGN_STATUS_VALUES, name="campaign_status", create_type=False)
EmailSendStatus = Enum(*EMAIL_SEND_STATUS_VALUES, name="email_send_status", create_type=False)


class Deal(Base, TimestampMixin):
    __tablename__ = "deals"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(DealStage, nullable=False, server_default="new")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign: Mapped[str | None] = mapped_column(Text, nullable=True)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    deal_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    deal_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Activity(Base):
    """Append-only (02 §10): a deal's own history, never edited or
    deleted — same two-layer enforcement `consent_records` uses."""

    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    deal_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Segment(Base, TimestampMixin):
    """`criteria` matches only non-PII lead/contact attributes (stage,
    UTM quintet) — 02 §10's own resolution of encrypted-email-vs-bulk-
    marketing (04 §4.4): a segment is computed, never a stored PII list."""

    __tablename__ = "segments"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    criteria: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class EmailTemplate(Base, TimestampMixin):
    __tablename__ = "email_templates"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    # Plain text only — services/email.py has never sent HTML.
    body_text: Mapped[str] = mapped_column(Text, nullable=False)


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("email_templates.id", ondelete="RESTRICT"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("segments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(CampaignStatus, nullable=False, server_default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailSend(Base):
    __tablename__ = "email_sends"
    __table_args__ = (
        Index("uq_email_sends_campaign_contact", "campaign_id", "contact_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(EmailSendStatus, nullable=False, server_default="queued")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class EmailEvent(Base):
    """Append-only: bounces and unsubscribes, never edited."""

    __tablename__ = "email_events"
    __table_args__ = (
        CheckConstraint("kind IN ('bounced', 'unsubscribed')", name="ck_email_events_kind"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email_send_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("email_sends.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Suppression(Base):
    """Keys on `email_blind_index`, never plaintext (02 §10) — a
    suppression check never has to decrypt anything."""

    __tablename__ = "suppressions"
    __table_args__ = (
        Index("uq_suppressions_tenant_email", "tenant_id", "email_blind_index", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email_blind_index: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = [
    "CAMPAIGN_STATUS_VALUES",
    "DEAL_STAGE_VALUES",
    "EMAIL_SEND_STATUS_VALUES",
    "Activity",
    "Campaign",
    "CampaignStatus",
    "Deal",
    "DealStage",
    "EmailEvent",
    "EmailSend",
    "EmailSendStatus",
    "EmailTemplate",
    "Note",
    "Segment",
    "Suppression",
    "Task",
]
