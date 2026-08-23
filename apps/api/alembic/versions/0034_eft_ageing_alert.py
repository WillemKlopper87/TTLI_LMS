"""EFT ageing alert (`docs/BACKLOG.md` R4; `02_DATA_MODEL.md` §12.4's
scheduled-integrity-jobs table names it explicitly: "Daily | Flag
approvals pending > 48 hours"). Until now this row in the design was the
one job never built — `bank-eft-automation.md` names it as *the* signal
that would tell the business to revisit manual EFT handling, and with
nothing computing it, that signal could never fire regardless of how
large the approval backlog grew.

`orders.ageing_alert_sent_at` marks an order alerted once — deliberately
not re-fired every day the same order stays stuck, the same "mark so it
can't repeat" shape `bookings.reminder_sent_at` (0027) already
established, for the same reason: a daily nag about the same stale order
trains staff to ignore the alert rather than act on it.

`due_eft_ageing_alerts` follows 0027's `due_workshop_reminders` idiom —
SECURITY DEFINER, `UPDATE ... RETURNING` inside `RETURN QUERY` so
"marked" and "returned to notify" can't drift apart — but returns one row
per *order*, not per (tenant, recipient). Staff to notify is looked up
separately, in the worker, through an ordinary tenant-scoped query: a
join against `role_assignments`/`role_permissions` inside this function
would mean a tenant with nobody currently holding `payment:approve`
produces zero rows and the order goes unflagged with no record at all —
exactly the silent-signal failure this migration exists to fix. Keeping
the mark-and-return step free of that join means the audit event (this
migration's actual durable signal) always fires; who gets pushed a
notification about it is a separate, best-effort concern.

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("ageing_alert_sent_at", pg.TIMESTAMP(timezone=True), nullable=True)
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION due_eft_ageing_alerts(threshold_hours int DEFAULT 48)
        RETURNS TABLE(
            tenant_id uuid, order_id uuid, payment_reference text, updated_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        BEGIN
            RETURN QUERY
            UPDATE orders o
            SET ageing_alert_sent_at = now()
            WHERE o.status IN ('eft_pending_approval', 'po_pending_approval')
              AND o.ageing_alert_sent_at IS NULL
              AND o.updated_at < now() - make_interval(hours => threshold_hours)
            RETURNING o.tenant_id, o.id, o.payment_reference::text, o.updated_at;
        END;
        $$;
        """
    )
    op.execute("REVOKE EXECUTE ON FUNCTION due_eft_ageing_alerts(int) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION due_eft_ageing_alerts(int) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS due_eft_ageing_alerts(int)")
    op.drop_column("orders", "ageing_alert_sent_at")
