"""Users.

Email is stored encrypted with a keyed blind index beside it — the ciphertext to
send mail, the index to log in. The domain is kept in clear because corporate
association and disposable-domain blocking need it, and a domain identifies an
employer, not a person.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, pk


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (
        # Unique per tenant, not globally: the same person may hold accounts
        # with two different corporate customers.
        Index("uq_users_tenant_email", "tenant_id", "email_blind_index", unique=True),
        Index("ix_users_guest_expiry", "guest_expires_at", postgresql_where=text("is_guest")),
        # 0028: registrations-in-period on the analytics dashboard.
        Index("ix_users_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    email_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    email_blind_index: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    email_domain: Mapped[str] = mapped_column(CITEXT, nullable=False, index=True)

    full_name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Null for magic-link-only and SSO users.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")

    is_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    guest_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    mfa_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_enforced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Separate from failed_login_count / locked_until: password and MFA
    # verification have different documented thresholds (10/15min vs 6/15min).
    mfa_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    mfa_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # BACKLOG T12 / 0046: 04_SECURITY_AND_COMPLIANCE.md §5.3's data-subject
    # rights. A hold blocks services.privacy.erase_user outright — it exists
    # for the case the security doc named and left open: a dispute or
    # investigation that must survive the subject's own erasure request.
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    legal_hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_hold_set_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_hold_set_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Set once, by services.privacy.erase_user, and never cleared — the
    # idempotency guard against a second erasure and the record of when
    # the anonymisation actually happened, distinct from `deleted_at`
    # (SoftDeleteMixin), which this table has never used for a live user.
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["User"]
