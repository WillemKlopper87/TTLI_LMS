"""Phase 3 remainder, part 1: refunds, credit notes, and `Idempotency-Key`
handling (02 §6.3/6.4, 03 §1.6).

Three new tables, all append-only (SELECT/INSERT only to `app_user`, the
same two-layer treatment `ledger_entries` already established in `0009`):

- `credit_notes` — 02 §6.4's accounting-correction document. Numbered
  through the exact same gapless, `SELECT ... FOR UPDATE`-locked counter
  `invoices` already uses (`invoice_number_counters`, keyed by `series` —
  no new counter table needed, just a second `series` value, `"CN"`).
  Full-invoice-only this sprint, the same "one complete vertical slice"
  narrowing `0009` already applied to EFT-only checkout — no line items,
  no partial amounts.
- `refunds` — 02 §6.3's record that money actually moved. Deliberately a
  separate table from `credit_notes`: one is the accounting correction,
  the other is the payment event, and `services/refunds.py::process_refund`
  always writes both together.
- `idempotency_keys` — 03 §1.6. No card/webhook endpoints exist yet
  (Payfast/Netcash still blocked on 01 §1.4's Phase 0 sandbox-credentials
  item), so this sprint's real callers are `POST /orders`, `POST
  /payments/{id}/{approve,reject}`, and the new `POST
  /orders/{id}/refund` — `core/idempotency.py`'s middleware is what scopes
  enforcement to exactly those routes; this table has no opinion on which
  endpoints use it.

No changes to `invoices`/`orders`/`entitlements` grants: `invoices` and
`orders` already have UPDATE from `0009`/`0021` (needed for
`invoice.status = 'credited'` and `order.status = 'refunded'`),
`entitlements` already has UPDATE from `0009` (needed for
`entitlement.revoked_at`). `InvoiceStatus.credited` and
`OrderStatus.refunded` are both enum values that have existed, unused,
since `0009`.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
NEW_TABLES = ("credit_notes", "refunds", "idempotency_keys")


def upgrade() -> None:
    op.create_table(
        "credit_notes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("series", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
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
    op.create_index("ix_credit_notes_tenant_id", "credit_notes", ["tenant_id"])
    op.create_index("ix_credit_notes_invoice_id", "credit_notes", ["invoice_id"])
    op.create_index(
        "uq_credit_notes_tenant_series_sequence",
        "credit_notes",
        ["tenant_id", "series", "sequence"],
        unique=True,
    )
    op.create_index(
        "uq_credit_notes_tenant_number", "credit_notes", ["tenant_id", "number"], unique=True
    )

    op.create_table(
        "refunds",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "credit_note_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("credit_notes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "processed_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
    op.create_index("ix_refunds_tenant_id", "refunds", ["tenant_id"])
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index("ix_refunds_credit_note_id", "refunds", ["credit_note_id"])

    op.create_table(
        "idempotency_keys",
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
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("path", sa.String(256), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", pg.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_idempotency_keys_tenant_id", "idempotency_keys", ["tenant_id"])
    op.create_index("ix_idempotency_keys_user_id", "idempotency_keys", ["user_id"])
    op.create_index(
        "uq_idempotency_keys_scope",
        "idempotency_keys",
        ["tenant_id", "user_id", "idempotency_key", "path"],
        unique=True,
    )

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        # Append-only, all three: a credit note or refund is immutable
        # financial history once written, and an idempotency record's
        # entire purpose is a faithful, unedited replay of what happened.
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"REVOKE SELECT, INSERT ON {table} FROM {APP_ROLE}")

    op.drop_table("idempotency_keys")
    op.drop_table("refunds")
    op.drop_table("credit_notes")
