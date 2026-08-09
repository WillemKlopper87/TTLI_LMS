"""Phase 3 sprint 1: commerce foundation + the EFT purchase path.

Scoped deliberately: 02 §6 documents the full commerce surface (products,
prices, orders, payments, invoices, ledger, tax_rules, subscriptions) and
03 §5 documents card (Payfast/Netcash), EFT and PO checkout. This migration
builds everything the *EFT* path needs end to end — the only purchase path
that needs no third-party account, unlike card (needs live Payfast/Netcash
sandbox credentials — 01 §1.4's Phase 0 outstanding list) or PO (deferred to
keep this migration to one complete vertical slice rather than three partial
ones). `orders.status`/`payments.status` still carry the full enum/value set
from 02 §3 and REQ-PAY-05 so a later sprint adding card/PO is a data change,
not a schema change.

Two decisions in 01 §1.4 block parts of commerce at the root — VAT
treatment (#2) and subscriptions in/out (#5). Both are handled the way
02 §6.5/§6.7 already say to, not guessed: `tax_rules` is data, seeded here
with only the one rate that is *not* in question (South African domestic
VAT, 15% at time of writing — 02 §6.5); nothing is seeded for international,
so `services/tax.py` refuses that case with a clear reason rather than
inventing a rate. Subscriptions aren't touched at all — no table, no flag —
until #5 closes.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = (
    "products",
    "prices",
    "tax_rules",
    "orders",
    "order_items",
    "payments",
    "invoice_number_counters",
    "invoices",
    "invoice_items",
    "ledger_entries",
    "entitlements",
)
APPEND_ONLY = ("ledger_entries",)

ORDER_STATUS_VALUES = (
    "draft",
    "pending_payment",
    "eft_pending_proof",
    "eft_pending_approval",
    "eft_rejected",
    "po_pending_approval",
    "paid",
    "fulfilled",
    "cancelled",
    "refunded",
)
INVOICE_STATUS_VALUES = (
    "draft",
    "issued",
    "partially_paid",
    "paid",
    "overdue",
    "cancelled",
    "credited",
)


def _uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


def upgrade() -> None:
    # create_type=False: created explicitly below, once. Without it,
    # SQLAlchemy also tries to create the type inline the first time it's
    # referenced in a Column (in the orders/invoices tables further down),
    # which collides with the explicit create.
    order_status = pg.ENUM(*ORDER_STATUS_VALUES, name="order_status", create_type=False)
    invoice_status = pg.ENUM(*INVOICE_STATUS_VALUES, name="invoice_status", create_type=False)
    order_status.create(op.get_bind())
    invoice_status.create(op.get_bind())

    op.create_table(
        "products",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # 'course' today; 'bundle'/'workshop'/'coaching' arrive with the
        # phases that sell them (4, 5) — the column doesn't need to change.
        sa.Column("kind", sa.String(32), nullable=False, server_default="course"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_index("uq_products_tenant_slug", "products", ["tenant_id", "slug"], unique=True)

    op.create_table(
        "prices",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_behaviour", sa.String(16), nullable=False, server_default="exclusive"),
        sa.Column(
            "valid_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_prices_tenant_id", "prices", ["tenant_id"])
    op.create_index("ix_prices_product_id", "prices", ["product_id"])

    op.create_table(
        "tax_rules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("jurisdiction", sa.String(8), nullable=False),
        # Null = matches any customer_type / product_kind. A specific match
        # is preferred over a wildcard — see services/tax.py's ORDER BY.
        sa.Column("customer_type", sa.String(32), nullable=True),
        sa.Column("product_kind", sa.String(32), nullable=True),
        sa.Column("rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("tax_code", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "valid_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_tax_rules_tenant_id", "tax_rules", ["tenant_id"])
    op.create_index("ix_tax_rules_jurisdiction", "tax_rules", ["tenant_id", "jurisdiction"])

    op.create_table(
        "orders",
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
        sa.Column("status", order_status, nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("tax_total", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("grand_total", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("po_number", sa.Text(), nullable=True),
        sa.Column("po_document_key", sa.Text(), nullable=True),
        sa.Column("payment_reference", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("uq_orders_payment_reference", "orders", ["payment_reference"], unique=True)

    op.create_table(
        "order_items",
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
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "price_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("prices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tax_rule_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_rules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("unit_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
    )
    op.create_index("ix_order_items_tenant_id", "order_items", ["tenant_id"])
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    op.create_table(
        "payments",
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
        # 'eft' today; 'payfast'/'netcash'/'po' arrive with those checkout
        # paths. REQ-PAY-05's state list, not a Postgres enum — 02 §3 does
        # not declare one for payments, unlike orders.status.
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_reference", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("proof_object_key", sa.Text(), nullable=True),
        sa.Column(
            "approved_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"])
    op.create_index("ix_payments_order_id", "payments", ["order_id"])

    # 02 §6.4: allocation happens inside the issuing transaction via a
    # per-(tenant_id, series) counter row locked with SELECT ... FOR UPDATE —
    # not a Postgres sequence, which is non-transactional and leaves gaps on
    # rollback. A gap is exactly what SARS objects to (REQ-PAY-09).
    op.create_table(
        "invoice_number_counters",
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("series", sa.String(32), primary_key=True),
        sa.Column("next_sequence", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )

    op.create_table(
        "invoices",
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
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("series", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", invoice_status, nullable=False, server_default="issued"),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("grand_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(14, 6), nullable=True),
        sa.Column("supplier_vat_number", sa.Text(), nullable=True),
        sa.Column("customer_vat_number", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"])
    op.create_index("ix_invoices_order_id", "invoices", ["order_id"])
    op.create_index(
        "uq_invoices_tenant_series_sequence",
        "invoices",
        ["tenant_id", "series", "sequence"],
        unique=True,
    )
    op.create_index("uq_invoices_tenant_number", "invoices", ["tenant_id", "number"], unique=True)

    op.create_table(
        "invoice_items",
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
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "tax_rule_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_rules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
    )
    op.create_index("ix_invoice_items_tenant_id", "invoice_items", ["tenant_id"])
    op.create_index("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"])

    # Append-only (02 §6.6) — same two-layer enforcement as audit_events and
    # consent_records: no UPDATE/DELETE grant, plus refuse_mutation().
    op.create_table(
        "ledger_entries",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("tax_code", sa.Text(), nullable=True),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("metadata", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )
    op.create_index("ix_ledger_entries_tenant_id", "ledger_entries", ["tenant_id"])
    op.create_index(
        "ix_ledger_entries_entity", "ledger_entries", ["tenant_id", "entity_type", "entity_id"]
    )
    op.execute(
        """
        CREATE TRIGGER ledger_entries_append_only
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION refuse_mutation();
        """
    )

    op.create_table(
        "entitlements",
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
            nullable=True,
        ),
        # No organisations table yet (Phase 5) — bare uuid, no FK, same
        # treatment as target_id below.
        sa.Column("organisation_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "source_order_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        # The course, path or feature key — polymorphic on `kind`, so no FK;
        # the course/path tables this could point at don't exist yet (Phase 4).
        sa.Column("target_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_entitlements_tenant_id", "entitlements", ["tenant_id"])
    op.create_index("ix_entitlements_user_id", "entitlements", ["user_id"])

    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        if table in APPEND_ONLY:
            op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        else:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    # South African domestic VAT — the one tax rate not in question. Nothing
    # is seeded for 'international': 01 §1.4 #2 is unsigned, and
    # services/tax.py refuses that case with a clear reason rather than
    # guessing one.
    conn = op.get_bind()
    for row in conn.execute(sa.text("SELECT id FROM tenants")).fetchall():
        tenant_id = row[0]
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text(
                "INSERT INTO tax_rules "
                "(id, tenant_id, jurisdiction, customer_type, product_kind, rate, tax_code, reason) "
                "VALUES (:i, :t, 'ZA', NULL, NULL, 0.15, 'ZA-VAT-STD', :reason)"
            ),
            {
                "i": _uuid7(),
                "t": tenant_id,
                "reason": (
                    "South African standard VAT rate, 15% at time of writing (02 §6.5). "
                    "Applies to both individual and registered-business customers "
                    "domestically — jurisdiction, not customer type, drives the SA rate."
                ),
            },
        )

    # One demo product + price per demo tenant, so the EFT purchase path is
    # exercisable without a product-authoring endpoint — deliberately out of
    # scope this sprint (that's admin catalogue tooling, not the purchase
    # flow itself). Scoped to 'demo'/'acme' by slug the same way 0006 scopes
    # its theme seed: those tenants don't exist in production (0002), so
    # this never reaches a real customer's data.
    for slug, name in (
        ("demo", "Executive Leadership Certificate"),
        ("acme", "Meridian Leadership Track"),
    ):
        tenant_id = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}
        ).scalar()
        if tenant_id is None:
            continue
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        product_id = _uuid7()
        conn.execute(
            sa.text(
                "INSERT INTO products (id, tenant_id, slug, name, description, kind, is_active) "
                "VALUES (:i, :t, 'executive-leadership-certificate', :n, "
                "'A demo product seeded so the EFT purchase path is exercisable end to end.', "
                "'course', true)"
            ),
            {"i": product_id, "t": tenant_id, "n": name},
        )
        conn.execute(
            sa.text(
                "INSERT INTO prices (id, tenant_id, product_id, currency, unit_amount, tax_behaviour) "
                "VALUES (:i, :t, :p, 'ZAR', 4500.00, 'exclusive')"
            ),
            {"i": _uuid7(), "t": tenant_id, "p": product_id},
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_append_only ON ledger_entries")
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("entitlements")
    op.drop_table("ledger_entries")
    op.drop_table("invoice_items")
    op.drop_table("invoices")
    op.drop_table("invoice_number_counters")
    op.drop_table("payments")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("tax_rules")
    op.drop_table("prices")
    op.drop_table("products")
    op.execute("DROP TYPE IF EXISTS invoice_status")
    op.execute("DROP TYPE IF EXISTS order_status")
