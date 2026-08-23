"""Commerce (02 §6): products, prices, tax rules, orders and the EFT
purchase path through to invoices, the append-only ledger, and
entitlements — the bridge to learning (Phase 4).

`order_status` and `invoice_status` are native Postgres enums, matching
02 §3's declared enum list; `payments.status` deliberately is not (§3 does
not declare a `payment_status` enum — REQ-PAY-05's state names live in a
plain column instead, same treatment as `AuditAction`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

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

# create_type=False: the migration creates these Postgres enum types
# explicitly, once. Without this, SQLAlchemy would try to (re)create them
# the first time they're used — the same collision the migration itself
# had to avoid.
OrderStatus = Enum(*ORDER_STATUS_VALUES, name="order_status", create_type=False)
InvoiceStatus = Enum(*INVOICE_STATUS_VALUES, name="invoice_status", create_type=False)


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (Index("uq_products_tenant_slug", "tenant_id", "slug", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, server_default="course")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # A product is sellable; a course is learnable (02 §5.1) — this is the
    # bridge. Nullable because Product.kind is not always "course" even
    # though that is the only kind seeded so far; entitlements.grant()
    # requires it to be set for kind="course" products (services/orders.py).
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=True
    )
    # Set only for kind="subscription" products — the same nullable-bridge
    # treatment as course_id above, just for the other sellable-wrapper case
    # (0021's migration docstring).
    subscription_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=True,
    )


class Price(Base, TimestampMixin):
    __tablename__ = "prices"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_behaviour: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="exclusive"
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaxRule(Base, TimestampMixin):
    __tablename__ = "tax_rules"
    __table_args__ = (Index("ix_tax_rules_jurisdiction", "tenant_id", "jurisdiction"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    jurisdiction: Mapped[str] = mapped_column(String(8), nullable=False)
    customer_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    tax_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("uq_orders_payment_reference", "payment_reference", unique=True),
        # 0028: the analytics dashboard's pipeline / paid-vs-waiting scans and
        # its by-organisation axis (routers/analytics.py).
        Index("ix_orders_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_orders_tenant_organisation", "tenant_id", "organisation_id"),
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
    status: Mapped[str] = mapped_column(OrderStatus, nullable=False, server_default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    tax_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    grand_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    po_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    po_document_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Set only for an organisation's seat purchase (0016) — an individual
    # order leaves this null, and services/orders.py branches fulfilment
    # on exactly this: null grants an entitlement to the buyer directly,
    # set grants seat capacity to the organisation instead.
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=True
    )
    # Set only for a subscription billing-period order (0021) — same
    # nullable-tag treatment as organisation_id above. Convention keeps
    # these mutually exclusive (an order is either a seat purchase or a
    # subscription period, never both), not a CHECK constraint, matching
    # how Entitlement.user_id/organisation_id's duality is already handled.
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=True
    )
    # 02 §12.4's EFT ageing alert (0034) marks an order here once it has
    # been flagged, so the daily sweep never re-alerts the same stuck
    # order — set only by due_eft_ageing_alerts(), never by application
    # code.
    ageing_alert_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    price_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prices.id", ondelete="RESTRICT"), nullable=False
    )
    tax_rule_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tax_rules.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    # 0028: payment-method breakdown on the analytics dashboard.
    __table_args__ = (
        Index("ix_payments_tenant_provider_created", "tenant_id", "provider", "created_at"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    proof_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaymentWebhook(Base, TimestampMixin):
    """02 §6.3: "`payment_webhooks.provider_event_id` is unique, which is
    the whole idempotency mechanism (§1.6)." `tenant_id` is resolved by
    the `resolve_payment_tenant` SECURITY DEFINER function (`0024`)
    *before* this row is ever written — a webhook arrives with no
    `X-Tenant-Host` a browser request would carry, so the normal
    hostname-based tenant resolution (`core/tenancy.py`) doesn't apply;
    this is the one request path that has to look itself up.

    `raw_payload_encrypted` (02 §6.3: "stored encrypted, since they carry
    billing details") holds the exact received form body, so a
    reconciliation dispute can be resolved against what the gateway
    actually sent, not a reconstruction of it.
    """

    __tablename__ = "payment_webhooks"
    __table_args__ = (
        Index("uq_payment_webhooks_provider_event", "provider", "provider_event_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_payload_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class InvoiceNumberCounter(Base):
    __tablename__ = "invoice_number_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    series: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("uq_invoices_tenant_series_sequence", "tenant_id", "series", "sequence", unique=True),
        Index("uq_invoices_tenant_number", "tenant_id", "number", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    series: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(InvoiceStatus, nullable=False, server_default="issued")
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    supplier_vat_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_vat_number: Mapped[str | None] = mapped_column(Text, nullable=True)


class CreditNote(Base, TimestampMixin):
    """02 §6.4's "correction means a credit note plus a new invoice" — the
    correction half. Full-invoice-only this sprint (`amount`/`tax_amount`
    always mirror the credited invoice's own totals exactly); a partial,
    line-item credit note is a real but separate scope this table doesn't
    yet model, the same class of narrowing Phase 3 sprint 1 already applied
    to EFT-only checkout. Numbered through the same gapless, locked counter
    `invoicing.py` uses for invoices, under its own `"CN"` series.

    Immutable once issued, like `Invoice` (02 §6.4) — `app_user` gets no
    UPDATE/DELETE grant, the same two-layer treatment `ledger_entries`
    already established.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        Index(
            "uq_credit_notes_tenant_series_sequence", "tenant_id", "series", "sequence", unique=True
        ),
        Index("uq_credit_notes_tenant_number", "tenant_id", "number", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    series: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Refund(Base, TimestampMixin):
    """02 §6.3's `refunds` table — the record that money actually moved.

    Deliberately distinct from `CreditNote`: a credit note is the
    accounting correction to an invoice; a refund is the payment event
    itself. `services/refunds.py::process_refund` always writes both
    together for this narrow full-refund path, but they answer different
    questions and an auditor needs both. No provider/gateway fields yet —
    like EFT approval, this records that a human moved the money outside
    the system (there is no live payment gateway to call), not that this
    system moved it. Append-only, same reasoning as `CreditNote` above.
    """

    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    credit_note_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("credit_notes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    processed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rule_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tax_rules.id", ondelete="RESTRICT"), nullable=False
    )
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class LedgerEntry(Base):
    """Append-only (02 §6.6) — no UPDATE/DELETE grant plus a raising
    trigger, same two-layer enforcement as AuditEvent and ConsentRecord."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("ix_ledger_entries_entity", "tenant_id", "entity_type", "entity_id"),
        # 0028: period-scoped revenue sums (payment_received / refund_issued).
        Index("ix_ledger_entries_tenant_type_created", "tenant_id", "entry_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    entry_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'")
    )


class Entitlement(Base):
    """The bridge between commerce and learning (02 §4.7). `target_id` is
    polymorphic on `kind` — no FK, since the course/path tables it can point
    at don't exist yet (Phase 4)."""

    __tablename__ = "entitlements"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Nullable — 02 §4.7: "organisation-level entitlements exist before
    # seat assignment." A null user_id + set organisation_id is the seat
    # pool itself (0016); a set user_id is one assigned seat drawn from it.
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=True
    )
    source_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "CreditNote",
    "Entitlement",
    "Invoice",
    "InvoiceItem",
    "InvoiceNumberCounter",
    "InvoiceStatus",
    "LedgerEntry",
    "Order",
    "OrderItem",
    "OrderStatus",
    "Payment",
    "PaymentWebhook",
    "Price",
    "Product",
    "Refund",
    "TaxRule",
]
