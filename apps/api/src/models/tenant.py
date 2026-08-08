"""Tenancy.

`tenants` and `tenant_domains` are deliberately NOT tenant-scoped and carry no
RLS. Hostname resolution has to run before a tenant is known, so the lookup
table cannot itself be behind the tenant filter.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = pk()
    slug: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")

    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    feature_flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # Per-tenant AI kill switch and budget (REQ-CRM-09). Present from the first
    # migration so the column does not have to be backfilled later.
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ai_monthly_token_budget: Mapped[int | None] = mapped_column(nullable=True)


class TenantDomain(Base, TimestampMixin):
    __tablename__ = "tenant_domains"
    __table_args__ = (
        # Exactly one primary hostname per tenant.
        Index(
            "uq_tenant_domains_primary",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    hostname: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tls_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")


__all__ = ["Tenant", "TenantDomain"]
