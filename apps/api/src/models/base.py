"""Declarative base and the mixins every table draws from."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.core.ids import uuid7


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class TenantMixin:
    """Carried by every tenant-scoped table. The RLS policies key on this column.

    ondelete is RESTRICT on purpose: deleting a tenant must be a deliberate,
    ordered teardown, not a cascade that silently removes financial records.
    """

    @classmethod
    def _tenant_fk(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


__all__ = ["Base", "SoftDeleteMixin", "TenantMixin", "TimestampMixin", "pk"]
