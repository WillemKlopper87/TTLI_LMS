"""P7: workshops end to end (`docs/BACKLOG.md` P7; `docs/01_PRD.md`
REQ-WS-01…09) — Phase 1 of a five-phase pass. All of this pass's schema
lands in this one migration even though the features it enables land
across later phases (P5's `0035` set the same precedent).

`session_facilitators` is additive alongside `workshop_sessions.
facilitator_id`, not a replacement for it (REQ-WS-02/03's multi-
facilitator gap) — the existing column stays the organiser/primary
pointer; this table is what makes "every facilitator on this session"
a real, queryable set instead of always being exactly one row. Every
existing session's sole facilitator is backfilled into it below, so
listing a session's facilitators is always this table alone.

`workshops.requires_credit` (default false) and `workshops.
meeting_provider` (default 'manual', reusing the `meeting_provider`
enum type `0018` already created for exactly this) are both opt-in,
per-workshop settings — every existing workshop keeps today's open/
free, manual-provider booking behaviour untouched.

`products.workshop_id` mirrors `products.learning_path_id`'s (`0035`)
exact nullable-bridge pattern — the credit-pack a workshop sells.

`bookings.consumed_entitlement_id` mirrors `path_enrolments.
entitlement_id`'s (`0035`) exact provenance-tracking pattern — which
workshop_credit entitlement a booking drew from, so cancelling refunds
the right one. Null for the (current) majority of bookings, which
don't require a credit at all.

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def _uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "session_facilitators",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workshop_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "facilitator_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("facilitators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_session_facilitators_tenant_id", "session_facilitators", ["tenant_id"])
    op.create_index("ix_session_facilitators_session_id", "session_facilitators", ["session_id"])
    op.create_index(
        "uq_session_facilitators",
        "session_facilitators",
        ["session_id", "facilitator_id"],
        unique=True,
    )

    op.execute("ALTER TABLE session_facilitators ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE session_facilitators FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON session_facilitators
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON session_facilitators TO {APP_ROLE}")

    # Backfill: every existing session's sole facilitator becomes its
    # first session_facilitators row. UUID v7 generated in Python
    # per row (0011/0021's own precedent), not gen_random_uuid() — this
    # table's ids stay k-sortable like every other table's.
    sessions = bind.execute(
        sa.text("SELECT id, tenant_id, facilitator_id FROM workshop_sessions")
    ).all()
    for session_id, tenant_id, facilitator_id in sessions:
        bind.execute(
            sa.text(
                "INSERT INTO session_facilitators (id, tenant_id, session_id, facilitator_id) "
                "VALUES (:id, :t, :s, :f)"
            ),
            {"id": _uuid7(), "t": tenant_id, "s": session_id, "f": facilitator_id},
        )

    op.add_column(
        "workshops",
        sa.Column("requires_credit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Raw DDL, not op.add_column(sa.Enum(...)): meeting_provider already
    # exists as a Postgres type (0018) — referencing it by name in raw
    # SQL sidesteps any ambiguity over whether SQLAlchemy's Enum wrapper
    # would try to (re-)create it (0035's migration docstring flags the
    # same class of pitfall for create_table; simplest to avoid it
    # entirely here by not going through the ORM-level type at all).
    op.execute(
        "ALTER TABLE workshops ADD COLUMN meeting_provider meeting_provider "
        "NOT NULL DEFAULT 'manual'"
    )

    op.add_column(
        "products",
        sa.Column(
            "workshop_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workshops.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    op.add_column(
        "bookings",
        sa.Column(
            "consumed_entitlement_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("bookings", "consumed_entitlement_id")
    op.drop_column("products", "workshop_id")
    op.drop_column("workshops", "meeting_provider")
    op.drop_column("workshops", "requires_credit")

    op.execute("ALTER TABLE session_facilitators NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON session_facilitators")
    op.execute(f"REVOKE ALL ON session_facilitators FROM {APP_ROLE}")
    op.drop_table("session_facilitators")
