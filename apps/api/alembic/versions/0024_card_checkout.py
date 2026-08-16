"""Phase 3 remainder, part 2: card checkout (03 §5.2/5.7) — the
provider-agnostic `PaymentProvider` protocol, a Payfast adapter (written
to spec, never verified against a live account — see
`services/payments/payfast.py`'s own docstring), and the `payment_webhooks`
table 02 §6.3 already named.

**The one genuinely new architectural piece**: `resolve_payment_tenant`.
Every other request path resolves its tenant from the Host header before
touching the database (`core/tenancy.py`); a payment gateway's webhook
has no such header — Payfast's servers know nothing about TTLI's
multi-tenancy. `payments` already carries `tenant_id` per row, so the
lookup itself is trivial; the problem is that `app_user`'s RLS policy
blocks it before tenant context is set, precisely because "find out which
tenant this belongs to" is what tenant context is for. Rather than hand
the webhook handler a superuser connection (a real, documented violation
of this project's own two-role convention — HANDOFF.md: "App = app_user
(RLS-bound). Migrations = ttli (superuser)"), this follows the exact
precedent `0005` already established for `extend_events_partitions`/
`purge_expired_auth_rows`: a narrow SECURITY DEFINER function, owned by
the migration role, granted EXECUTE to `app_user` and nothing else. It
returns only a UUID — never a row, never anything from `payments` itself
— so the privilege it grants is exactly "resolve a tenant," not "read
across tenants."

`payment_webhooks` is append-only, same two-layer treatment `ledger_entries`
established in `0009` — a received notification is a fact, not something
this application ever has reason to edit.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.create_table(
        "payment_webhooks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=False),
        sa.Column("raw_payload_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_payment_webhooks_tenant_id", "payment_webhooks", ["tenant_id"])
    op.create_index("ix_payment_webhooks_payment_id", "payment_webhooks", ["payment_id"])
    op.create_index(
        "uq_payment_webhooks_provider_event",
        "payment_webhooks",
        ["provider", "provider_event_id"],
        unique=True,
    )

    op.execute("ALTER TABLE payment_webhooks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payment_webhooks FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payment_webhooks
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON payment_webhooks TO {APP_ROLE}")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION resolve_payment_tenant(target_payment_id uuid)
        RETURNS uuid
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT tenant_id FROM payments WHERE id = target_payment_id
        $$
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION resolve_payment_tenant(uuid) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION resolve_payment_tenant(uuid) FROM {APP_ROLE}")
    op.execute("DROP FUNCTION IF EXISTS resolve_payment_tenant(uuid)")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payment_webhooks")
    op.execute(f"REVOKE SELECT, INSERT ON payment_webhooks FROM {APP_ROLE}")
    op.drop_table("payment_webhooks")
