"""Web Push (01 §5.9) — payment approved/rejected, certificate/badge
issued, and a workshop-starting-soon reminder, per the product owner's
explicit choice of which three triggers this covers. Unlike Payfast/
Spotify, nothing here is blocked on a third-party account: VAPID is a
self-generated keypair (`services/push.py`'s module docstring has the
one-liner), so this ships genuinely functional once
`settings.vapid_public_key`/`vapid_private_key` are set — still empty by
default, the same graceful-degradation shape, but the blocker is
"nobody generated one yet," not "waiting on an external party."

`push_subscriptions` is tenant-scoped/RLS, the standard shape (unique on
`endpoint` — a given browser-push endpoint URL belongs to exactly one
subscription, re-subscribing the same device upserts rather than
duplicating). `bookings.reminder_sent_at` is a plain nullable column, not
a new table — one reminder per booking is the whole requirement, no
history to keep.

`due_workshop_reminders` follows `0005`'s `SECURITY DEFINER`
maintenance-function idiom, same as `0021`/`0025` — but unlike those,
which only report *how many* rows changed, this one has to hand back
*which* rows (tenant/user/session/title) so the worker can actually
enqueue a push per reminder; `UPDATE ... FROM ... RETURNING` inside
`RETURN QUERY` does the "mark reminded" and "who to notify" in one
atomic statement, so a reminder can never be marked sent without also
being returned for sending (or vice versa).

Revision ID: 0027
Revises: 0026
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh_key", sa.Text(), nullable=False),
        sa.Column("auth_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_push_subscriptions_tenant_id", "push_subscriptions", ["tenant_id"])
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_index(
        "uq_push_subscriptions_endpoint", "push_subscriptions", ["endpoint"], unique=True
    )

    op.execute("ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE push_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON push_subscriptions
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    # UPDATE included: services/push.py::subscribe upserts on endpoint —
    # re-subscribing the same device rewrites p256dh/auth in place.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON push_subscriptions TO {APP_ROLE}")

    op.add_column(
        "bookings", sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION due_workshop_reminders(window_hours int DEFAULT 24)
        RETURNS TABLE(
            tenant_id uuid, user_id uuid, session_id uuid,
            workshop_title text, starts_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        BEGIN
            RETURN QUERY
            UPDATE bookings b
            SET reminder_sent_at = now()
            FROM workshop_sessions ws
            JOIN workshops w ON w.id = ws.workshop_id
            WHERE b.session_id = ws.id
              AND b.status = 'registered'
              AND b.reminder_sent_at IS NULL
              AND ws.starts_at BETWEEN now() AND now() + make_interval(hours => window_hours)
            RETURNING b.tenant_id, b.user_id, b.session_id, w.title, ws.starts_at;
        END;
        $$;
        """
    )
    op.execute("REVOKE EXECUTE ON FUNCTION due_workshop_reminders(int) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION due_workshop_reminders(int) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS due_workshop_reminders(int)")
    op.drop_column("bookings", "reminder_sent_at")
    op.drop_table("push_subscriptions")
