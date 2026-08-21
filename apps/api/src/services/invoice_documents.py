"""Reading invoices back, and rendering one as a tax invoice PDF
(`docs/BACKLOG.md` P6 — feature-matrix gaps #34 and #39).

The invoicing *write* path (`services/invoicing.py`) has been gapless and
audit-correct since Phase 3, but nothing could read an invoice back: a
buyer could not fetch their own, and finance could not export a period.
The rigorous ledger work was invisible to the people it was for.

The PDF is rendered **on demand from stored columns, never stored**.
Certificates take the opposite approach — rendered once, written to
object storage, served by signed URL — and the difference is deliberate:
a certificate embeds a QR code and a verification token and is a
credential someone may present years later, so the artefact itself is
the record. An invoice's record is the row; the document is a view of
it. Rendering on demand means no `pdf_object_key` column, no migration,
no risk of a stored PDF drifting from the figures it claims to show.

`supplier_vat_number`/`customer_vat_number` are read from the invoice's
own snapshot columns rather than joined from the tenant or organisation
(02 §6.4): a customer's VAT number can change after issue, and a
document that showed today's number would misstate a past transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.commerce import Invoice, InvoiceItem
from src.schemas.commerce import (
    InvoiceDetailResponse,
    InvoiceItemResponse,
)


async def list_invoices(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 200,
) -> list[InvoiceDetailResponse]:
    """`user_id` None means "every invoice in the tenant" — the finance
    view. A concrete id scopes to that buyer's own orders, which is what
    a learner or an organisation admin gets. The caller decides which by
    holding `order:view` or not; this function does not make that call.
    """
    stmt = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if user_id is not None:
        from src.models.commerce import Order

        stmt = stmt.join(Order, Order.id == Invoice.order_id).where(Order.user_id == user_id)
    if date_from is not None:
        stmt = stmt.where(Invoice.issued_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Invoice.issued_at < date_to)

    invoices = (
        (await session.execute(stmt.order_by(Invoice.issued_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    if not invoices:
        return []

    items = (
        (
            await session.execute(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id.in_([i.id for i in invoices]))
                .order_by(InvoiceItem.id)
            )
        )
        .scalars()
        .all()
    )
    by_invoice: dict[uuid.UUID, list[InvoiceItem]] = {}
    for item in items:
        by_invoice.setdefault(item.invoice_id, []).append(item)

    return [_detail(invoice, by_invoice.get(invoice.id, [])) for invoice in invoices]


async def get_invoice(
    session: AsyncSession, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID
) -> tuple[Invoice, list[InvoiceItem]] | None:
    invoice = (
        await session.execute(
            select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        return None
    items = (
        (
            await session.execute(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id == invoice.id)
                .order_by(InvoiceItem.id)
            )
        )
        .scalars()
        .all()
    )
    return invoice, list(items)


def _detail(invoice: Invoice, items: list[InvoiceItem]) -> InvoiceDetailResponse:
    return InvoiceDetailResponse(
        id=str(invoice.id),
        number=invoice.number,
        status=invoice.status,
        issued_at=invoice.issued_at,
        currency=invoice.currency,
        subtotal=invoice.subtotal,
        tax_total=invoice.tax_total,
        grand_total=invoice.grand_total,
        supplier_vat_number=invoice.supplier_vat_number,
        customer_vat_number=invoice.customer_vat_number,
        order_id=str(invoice.order_id),
        items=[
            InvoiceItemResponse(
                description=item.description,
                quantity=item.quantity,
                unit_amount=item.unit_amount,
                tax_amount=item.tax_amount,
                line_total=item.line_total,
            )
            for item in items
        ],
    )


def detail(invoice: Invoice, items: list[InvoiceItem]) -> InvoiceDetailResponse:
    return _detail(invoice, items)


def _money(currency: str, amount: Decimal) -> str:
    return f"{currency} {amount:,.2f}"


def render_invoice_pdf(
    *,
    invoice: Invoice,
    items: list[InvoiceItem],
    supplier_name: str,
    buyer_email: str | None,
) -> bytes:
    """Portrait A4, drawn directly, same approach as
    `credentials.render_certificate_pdf` — the layout is fixed and small,
    so a template engine would be a dependency earning nothing.

    The document says **TAX INVOICE** and carries the fields that makes
    it one: a sequential number, the issue date, both VAT numbers where
    they exist, per-line VAT, and VAT shown separately from the subtotal.
    Nothing here computes tax; every figure is read from the row the
    tax engine already wrote.
    """
    buffer = BytesIO()
    width, height = A4
    pdf = canvas.Canvas(buffer, pagesize=A4)

    left = 20 * mm
    right = width - 20 * mm
    y = height - 25 * mm

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(left, y, "TAX INVOICE")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawRightString(right, y, invoice.number)

    y -= 6 * mm
    pdf.setStrokeColorRGB(0.56, 0.08, 0.11)
    pdf.setLineWidth(1.5)
    pdf.line(left, y, right, y)

    y -= 10 * mm
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, y, supplier_name)
    pdf.setFont("Helvetica", 9)
    if invoice.supplier_vat_number:
        y -= 5 * mm
        pdf.drawString(left, y, f"VAT registration: {invoice.supplier_vat_number}")

    y -= 10 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(left, y, "Billed to")
    pdf.setFont("Helvetica", 9)
    y -= 5 * mm
    pdf.drawString(left, y, buyer_email or "(no address on file)")
    if invoice.customer_vat_number:
        y -= 5 * mm
        pdf.drawString(left, y, f"VAT registration: {invoice.customer_vat_number}")

    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(right, height - 45 * mm, f"Issued: {invoice.issued_at:%d %B %Y}")
    pdf.drawRightString(right, height - 50 * mm, f"Status: {invoice.status}")

    y -= 14 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(left, y, "Description")
    pdf.drawRightString(right - 90 * mm, y, "Qty")
    pdf.drawRightString(right - 60 * mm, y, "Unit")
    pdf.drawRightString(right - 30 * mm, y, "VAT")
    pdf.drawRightString(right, y, "Line total")
    y -= 2 * mm
    pdf.setStrokeColorRGB(0.8, 0.8, 0.8)
    pdf.setLineWidth(0.5)
    pdf.line(left, y, right, y)

    pdf.setFont("Helvetica", 9)
    for item in items:
        y -= 6 * mm
        if y < 45 * mm:
            # A long order should not silently lose its tail off the
            # bottom of page one.
            pdf.showPage()
            y = height - 25 * mm
            pdf.setFont("Helvetica", 9)
        pdf.drawString(left, y, item.description[:58])
        pdf.drawRightString(right - 90 * mm, y, str(item.quantity))
        pdf.drawRightString(right - 60 * mm, y, f"{item.unit_amount:,.2f}")
        pdf.drawRightString(right - 30 * mm, y, f"{item.tax_amount:,.2f}")
        pdf.drawRightString(right, y, f"{item.line_total:,.2f}")

    y -= 4 * mm
    pdf.line(right - 70 * mm, y, right, y)
    y -= 6 * mm
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(right - 30 * mm, y, "Subtotal")
    pdf.drawRightString(right, y, _money(invoice.currency, invoice.subtotal))
    y -= 5 * mm
    pdf.drawRightString(right - 30 * mm, y, "VAT")
    pdf.drawRightString(right, y, _money(invoice.currency, invoice.tax_total))
    y -= 6 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(right - 30 * mm, y, "Total")
    pdf.drawRightString(right, y, _money(invoice.currency, invoice.grand_total))

    pdf.setFont("Helvetica", 7)
    pdf.drawString(
        left,
        15 * mm,
        f"Invoice {invoice.number} · issued {invoice.issued_at:%Y-%m-%d} · "
        "figures as recorded at issue",
    )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


__all__ = ["detail", "get_invoice", "list_invoices", "render_invoice_pdf"]
