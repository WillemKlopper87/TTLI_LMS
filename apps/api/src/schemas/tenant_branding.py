"""Branding and custom-domain shapes (`docs/BACKLOG.md` P3, gaps #44/#45)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BrandingResponse(BaseModel):
    logo_url: str | None
    primary_color: str | None
    secondary_color: str | None
    login_background_url: str | None
    support_email: str | None
    email_footer_text: str | None


class BrandingUpdateRequest(BaseModel):
    """Every field optional and nullable: an unset field is left alone,
    an explicit null clears it. Colours are contrast-checked server-side
    rather than accepted and rendered unreadable — see
    `services/tenant_branding.py`.
    """

    primary_color: str | None = None
    secondary_color: str | None = None
    login_background_url: str | None = Field(default=None, max_length=500)
    support_email: str | None = Field(default=None, max_length=200)
    email_footer_text: str | None = Field(default=None, max_length=500)


class DomainRow(BaseModel):
    id: uuid.UUID
    hostname: str
    is_primary: bool
    verified_at: datetime | None
    tls_status: str
    # What the owner must publish in DNS to prove the hostname is theirs.
    # Derived, not stored, and shown on every read so the screen can
    # repeat the instruction without a "reveal token" round-trip.
    dns_txt_record: str


class DomainsResponse(BaseModel):
    items: list[DomainRow]
    # Stated plainly rather than implied by an absent button: the check
    # itself is Phase 7 work, so nothing here should read as "verified".
    verification_available: bool


class AddDomainRequest(BaseModel):
    hostname: str = Field(min_length=4, max_length=253)


__all__ = [
    "AddDomainRequest",
    "BrandingResponse",
    "BrandingUpdateRequest",
    "DomainRow",
    "DomainsResponse",
]
