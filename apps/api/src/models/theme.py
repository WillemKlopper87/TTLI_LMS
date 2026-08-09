"""Tenant themes (02 §4.3). One row per tenant; theming features are Phase 5,
the read contract exists from Phase 1."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class TenantTheme(Base, TimestampMixin):
    __tablename__ = "tenant_themes"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    secondary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    login_background_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    email_footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["TenantTheme"]
