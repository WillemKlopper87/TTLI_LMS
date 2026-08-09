"""Sequential, gapless invoice numbering (02 §6.4, REQ-PAY-09).

Allocation happens inside the issuing transaction via a per-`(tenant_id,
series)` counter row locked with `SELECT ... FOR UPDATE` — not a Postgres
sequence, which is non-transactional and leaves gaps on rollback, and a gap
is exactly what SARS objects to. A failed issue rolls the counter back with
the rest of the transaction, same as everything else in it.

An issued invoice is immutable (02 §6.4) — nothing in this module updates
one after `issue()` returns. Correction is a credit note plus a new
invoice, not implemented in this sprint (STATUS.md tracks it as deferred).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.ids import uuid7
from src.models.commerce import Invoice, InvoiceItem, Order, OrderItem, Product

# One series today. Splitting by financial year ("INV-2026") arrives if/when
# the customer's accountants require it — not asked for yet.
DEFAULT_SERIES = "INV"


async def _next_sequence(session: AsyncSession, *, tenant_id: uuid.UUID, series: str) -> int:
    await session.execute(
        text(
            "INSERT INTO invoice_number_counters (tenant_id, series, next_sequence) "
            "VALUES (:t, :s, 1) ON CONFLICT (tenant_id, series) DO NOTHING"
        ),
        {"t": tenant_id, "s": series},
    )
    locked = (
        await session.execute(
            text(
                "SELECT next_sequence FROM invoice_number_counters "
                "WHERE tenant_id = :t AND series = :s FOR UPDATE"
            ),
            {"t": tenant_id, "s": series},
        )
    ).scalar_one()
    await session.execute(
        text(
            "UPDATE invoice_number_counters SET next_sequence = next_sequence + 1 "
            "WHERE tenant_id = :t AND series = :s"
        ),
        {"t": tenant_id, "s": series},
    )
    return int(locked)


async def issue(
    session: AsyncSession, *, tenant_id: uuid.UUID, order: Order, supplier_vat_number: str | None
) -> Invoice:
    series = DEFAULT_SERIES
    sequence = await _next_sequence(session, tenant_id=tenant_id, series=series)
    number = f"{series}-{sequence:06d}"

    invoice = Invoice(
        id=uuid7(),
        tenant_id=tenant_id,
        order_id=order.id,
        number=number,
        series=series,
        sequence=sequence,
        status="issued",
        currency=order.currency,
        subtotal=order.subtotal,
        tax_total=order.tax_total,
        grand_total=order.grand_total,
        supplier_vat_number=supplier_vat_number,
    )
    session.add(invoice)
    await session.flush()

    items = (
        await session.execute(
            select(OrderItem, Product)
            .join(Product, Product.id == OrderItem.product_id)
            .where(OrderItem.order_id == order.id)
        )
    ).all()
    for order_item, product in items:
        session.add(
            InvoiceItem(
                id=uuid7(),
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                description=product.name,
                quantity=order_item.quantity,
                unit_amount=order_item.unit_amount,
                tax_amount=order_item.tax_amount,
                tax_rule_id=order_item.tax_rule_id,
                line_total=order_item.line_total,
            )
        )
    await session.flush()
    return invoice


__all__ = ["DEFAULT_SERIES", "issue"]
