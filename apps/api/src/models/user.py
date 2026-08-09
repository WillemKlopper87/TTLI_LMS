"""Users.

Email is stored encrypted with a keyed blind index beside it — the ciphertext to
send mail, the index to log in. The domain is kept in clear because corporate
association and disposable-domain blocking need it, and a domain identifies an
employer, not a person.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, text
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


__all__ = ["User"]
