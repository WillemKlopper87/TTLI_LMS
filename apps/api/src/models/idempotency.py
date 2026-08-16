"""`Idempotency-Key` handling (03 §1.6).

Deliberately separate from `commerce.py` even though every current caller
is a commerce endpoint (`POST /orders`, `POST /payments/*`, `POST
/orders/{id}/refund`): this is generic API infrastructure that a future
webhook or another mutating endpoint can reuse, not a commerce concept
itself — the same reason `audit.py` sits apart from the domain models it
happens to be triggered by. `core/idempotency.py`'s scoped-route table is
what currently limits it to commerce.

One row per (tenant, caller, key, path): the same key value legitimately
means different things on different endpoints and for different callers,
so all three are part of the identity, not just the client-supplied key.
Append-only — a stored replay is a record of what actually happened and is
never edited; a retention sweep for old rows is a real, separate,
not-yet-built follow-up (STATUS.md tracks it), not something this table's
shape blocks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, pk


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        Index(
            "uq_idempotency_keys_scope",
            "tenant_id",
            "user_id",
            "idempotency_key",
            "path",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Client-supplied. 03 §1.6/the API spec's header table call it a
    # "Client-generated UUID" but this stores whatever string arrives
    # rather than validating UUID shape — the replay-detection semantics
    # (same key + same body → same response; same key + different body →
    # 409) hold regardless of the key's own format.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(256), nullable=False)
    # sha256 hex of the exact raw request body bytes — "a hash of the
    # request body" per spec, literally, not a normalised/parsed form.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    # Null for a 204. Stored exactly as the client received it, so a
    # replay is byte-identical, not just status-identical.
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = ["IdempotencyKey"]
