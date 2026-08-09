"""First-party analytics events (02_DATA_MODEL.md §11.1).

Partitioned monthly by `created_at` — retrofitting partitioning onto a hot,
ever-growing table later is painful, so it starts partitioned. The parent
table (this model) carries RLS and every index; individual month partitions
(`events_2026_08`, ...) are pure DDL managed by the migration and
`alembic/env.py`'s include_object hook, not modelled here — see
0004_events_partitioned.py for how the partition range is bootstrapped and
where the ongoing job to extend it belongs.

`consent_marketing` / `consent_analytics` are captured on the row and have no
default: a later withdrawal must not retroactively change what was lawfully
collected, and nothing may silently assume consent either way.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.ids import uuid7
from src.models.base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_events_tenant_event_name", "tenant_id", "event_name"),
        Index("ix_events_anonymous_id", "anonymous_id"),
        Index("ix_events_user_id", "user_id"),
        Index("ix_events_session_id", "session_id"),
    )

    # Composite primary key (id, created_at): Postgres requires the partition
    # key in every unique constraint on a partitioned table, so created_at
    # joins id here rather than via a separate PrimaryKeyConstraint.
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    anonymous_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # SET NULL, not RESTRICT like every other user_id FK in this schema:
    # events are analytics history that must outlive a POPIA erasure of the
    # user who generated them (04_SECURITY_AND_COMPLIANCE.md §5.3).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    event_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    utm_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)

    locale: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    consent_marketing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    consent_analytics: Mapped[bool] = mapped_column(Boolean, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), primary_key=True
    )


__all__ = ["Event"]
