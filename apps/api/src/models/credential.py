"""Certificates and badges (02 §8). See 0014's migration docstring for
why `verification_token` is encrypted + blind-indexed (reconstructable,
unlike a hashed magic-link/refresh token) while `certificate_number` is
not encrypted at all (public serial, not a secret), and for the
global-vs-tenant-scoped split.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

CREDENTIAL_STATUS_VALUES = ("valid", "expired", "revoked")
CredentialStatus = Enum(*CREDENTIAL_STATUS_VALUES, name="credential_status", create_type=False)


class CertificateTemplate(Base, TimestampMixin):
    __tablename__ = "certificate_templates"

    id: Mapped[uuid.UUID] = pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # The issuing organisation — distinct from signatory_name, the person
    # who signs. See 0014's migration docstring for why these aren't the
    # same field.
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    signatory_name: Mapped[str] = mapped_column(Text, nullable=False)
    signatory_title: Mapped[str] = mapped_column(Text, nullable=False)
    cpd_points: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        Index("uq_certificates_enrolment", "enrolment_id", unique=True),
        Index("uq_certificates_number", "certificate_number", unique=True),
        Index("uq_certificates_token_blind_index", "verification_token_blind_index", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("enrolments.id", ondelete="CASCADE"), nullable=False
    )
    certificate_template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("certificate_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    certificate_number: Mapped[str] = mapped_column(Text, nullable=False)
    # Encrypted + blind-indexed, not one-way hashed — see 0014's migration
    # docstring for why this needs to be reconstructable later (LinkedIn
    # share), unlike a magic-link/refresh token.
    verification_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    verification_token_blind_index: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(CredentialStatus, nullable=False, server_default="valid")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pdf_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, server_default="private")
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class BadgeTemplate(Base, TimestampMixin):
    __tablename__ = "badge_templates"

    id: Mapped[uuid.UUID] = pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    criteria: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str | None] = mapped_column(Text, nullable=True)


class Badge(Base):
    __tablename__ = "badges"
    __table_args__ = (Index("uq_badges_enrolment", "enrolment_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("enrolments.id", ondelete="CASCADE"), nullable=False
    )
    badge_template_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("badge_templates.id", ondelete="RESTRICT"), nullable=False
    )
    certificate_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("certificates.id", ondelete="SET NULL"), nullable=True
    )
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, server_default="private")
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CredentialVerification(Base):
    """Append-only in spirit (services/credentials.py only ever inserts)
    but, like `video_heartbeats` and `events`, given the plain grant
    rather than a second trigger-enforced mechanism — see 0013/0004's
    precedent for the same tradeoff."""

    __tablename__ = "credential_verifications"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    certificate_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("certificates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    token_blind_index: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = [
    "Badge",
    "BadgeTemplate",
    "Certificate",
    "CertificateTemplate",
    "CredentialStatus",
    "CredentialVerification",
]
