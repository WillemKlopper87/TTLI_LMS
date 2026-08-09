"""Contacts: a not-yet-registered person captured by lead generation.

Same encrypt-what-you-read pattern as users (src/models/user.py) — email and
name are PII that must be read back (to reply, to greet), so they are
encrypted with a blind index alongside, not hashed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, LargeBinary
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("uq_contacts_tenant_email", "tenant_id", "email_blind_index", unique=True),
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

    first_name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    last_name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


__all__ = ["Contact"]
