"""Per-tenant identity-provider configuration (`0033`).

One row per tenant, enforced by a unique index: a login page cannot ask
"which of your two identity providers did you mean?" before there is a
session to ask.

The client secret is stored encrypted like every other secret in this
schema. It is the credential that lets a holder impersonate the whole
tenant to its own IdP, so it never sits in clear at rest.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class TenantIdpConfig(Base, TimestampMixin):
    __tablename__ = "tenant_idp_configs"
    __table_args__ = (Index("uq_tenant_idp_configs_tenant", "tenant_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    protocol: Mapped[str] = mapped_column(String(16), nullable=False, server_default="oidc")
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # The account-takeover guard: JIT provisioning trusts the IdP's email
    # claim, so an email outside these domains is never provisioned.
    allowed_email_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    group_role_map: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    default_role_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


__all__ = ["TenantIdpConfig"]
