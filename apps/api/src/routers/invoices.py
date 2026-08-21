"""Reading invoices, and the accounting exports
(`docs/BACKLOG.md` P6 — feature-matrix gaps #34 "sequential auditable
invoicing" and #39 "accounting export (CSV)").

Invoicing has been gapless and ledger-backed since Phase 3, but was
write-only: a buyer could not fetch the invoice for something they had
paid for, and finance could not export a period. `05_COMMERCIAL.md` §3
sells "Accounting export (CSV)" from the Team tier up, so this closes a
promise as well as a gap.

**Two audiences, one endpoint each way round.** A buyer sees their own
invoices with no permission at all — they are documents about that
person's own money. Everything wider is gated: `order:view` to read the
whole tenant's invoices, and the CSV exports sit behind
`invoice:create`, the permission `finance` already holds, because an
accounting export is a finance function rather than a reporting one.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Query, Response

from src.core.crypto import CryptoBox
from src.core.deps import CryptoDep, PrincipalDep, SessionDep, TenantDep
from src.core.errors import NotFound
from src.models.commerce import Invoice, InvoiceItem, LedgerEntry, Order
from src.models.user import User
from src.schemas.commerce import InvoiceDetailResponse, InvoicesPageResponse
from src.services import invoice_documents

router = APIRouter(tags=["commerce"])

READ_ALL = "order:view"
EXPORT = "invoice:create"

INVOICE_CSV_HEADER = (
    "number",
    "issued_at",
    "status",
    "currency",
    "subtotal",
    "tax_total",
    "grand_total",
    "supplier_vat_number",
    "customer_vat_number",
    "order_id",
)

LEDGER_CSV_HEADER = (
    "created_at",
    "entry_type",
    "entity_type",
    "entity_id",
    "currency",
    "amount",
    "vat_amount",
    "tax_code",
    "reference",
)


def _window(
    date_from: date | None, date_to: date | None
) -> tuple[datetime | None, datetime | None]:
    """`to` is inclusive of its whole day, matching the analytics
    endpoints' convention so a finance user asking both for "August"
    gets the same August."""
    from datetime import UTC, timedelta

    start = datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC) if date_to else None
    return start, end


@router.get(
    "/invoices",
    response_model=InvoicesPageResponse,
    summary="Invoices — your own by default, the tenant's with order:view",
)
async def list_invoices(
    principal: PrincipalDep,
    session: SessionDep,
    mine: Annotated[
        bool, Query(description="False, with order:view, returns every invoice in the tenant")
    ] = True,
    date_from: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
    date_to: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
) -> InvoicesPageResponse:
    if not mine:
        principal.require(READ_ALL)
    start, end = _window(date_from, date_to)
    return InvoicesPageResponse(
        items=await invoice_documents.list_invoices(
            session,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id if mine else None,
            date_from=start,
            date_to=end,
        )
    )


# Declared BEFORE /invoices/{invoice_id}: FastAPI matches in declaration
# order, so a literal path that could also read as a path parameter has to
# come first. Registered the other way round, "export.csv" is parsed as an
# invoice id and the caller gets a 422 about UUID formatting instead of
# their CSV — which a test now pins.
@router.get(
    "/invoices/export.csv",
    summary="Accounting export: every invoice in the window",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_invoices(
    principal: PrincipalDep,
    session: SessionDep,
    date_from: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
    date_to: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
) -> Response:
    principal.require(EXPORT)
    start, end = _window(date_from, date_to)
    rows = await invoice_documents.list_invoices(
        session,
        tenant_id=principal.tenant_id,
        user_id=None,
        date_from=start,
        date_to=end,
        limit=10_000,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(INVOICE_CSV_HEADER)
    for row in rows:
        writer.writerow(
            (
                row.number,
                row.issued_at.isoformat(),
                row.status,
                row.currency,
                f"{row.subtotal:.2f}",
                f"{row.tax_total:.2f}",
                f"{row.grand_total:.2f}",
                row.supplier_vat_number or "",
                row.customer_vat_number or "",
                row.order_id,
            )
        )
    return _csv(buffer.getvalue(), "invoices.csv")


@router.get(
    "/ledger/export.csv",
    summary="Accounting export: the append-only ledger for the window",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_ledger(
    principal: PrincipalDep,
    session: SessionDep,
    date_from: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
    date_to: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
) -> Response:
    """The ledger, not a re-derivation of it: this is the same
    append-only table `services/analytics.py` computes revenue from, so
    an accountant reconciling the export against the dashboard is
    comparing one source with itself."""
    principal.require(EXPORT)
    from sqlalchemy import select

    start, end = _window(date_from, date_to)
    stmt = select(LedgerEntry).where(LedgerEntry.tenant_id == principal.tenant_id)
    if start is not None:
        stmt = stmt.where(LedgerEntry.created_at >= start)
    if end is not None:
        stmt = stmt.where(LedgerEntry.created_at < end)
    entries = (await session.execute(stmt.order_by(LedgerEntry.created_at).limit(50_000))).scalars()

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(LEDGER_CSV_HEADER)
    for entry in entries:
        writer.writerow(
            (
                entry.created_at.isoformat(),
                entry.entry_type,
                entry.entity_type,
                str(entry.entity_id),
                entry.currency,
                f"{entry.amount:.2f}",
                f"{entry.vat_amount:.2f}",
                entry.tax_code or "",
                entry.reference or "",
            )
        )
    return _csv(buffer.getvalue(), "ledger.csv")


async def _load_owned(
    session: SessionDep, principal: PrincipalDep, invoice_id: uuid.UUID
) -> tuple[Invoice, list[InvoiceItem]]:
    found = await invoice_documents.get_invoice(
        session, tenant_id=principal.tenant_id, invoice_id=invoice_id
    )
    if found is None:
        raise NotFound("No such invoice.")
    invoice, items = found
    order = await session.get(Order, invoice.order_id)
    # Someone else's invoice is not merely forbidden to read, it is not
    # theirs to know exists — but the tenant's finance staff must be able
    # to open any of them.
    if order is None or order.user_id != principal.user_id:
        principal.require(READ_ALL)
    return invoice, items


@router.get(
    "/invoices/{invoice_id}",
    response_model=InvoiceDetailResponse,
    summary="One invoice with its lines",
)
async def get_invoice(
    invoice_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> InvoiceDetailResponse:
    invoice, items = await _load_owned(session, principal, invoice_id)
    return invoice_documents.detail(invoice, items)


@router.get(
    "/invoices/{invoice_id}/pdf",
    summary="The tax invoice as a PDF, rendered on demand",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_invoice_pdf(
    invoice_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    tenant: TenantDep,
) -> Response:
    invoice, items = await _load_owned(session, principal, invoice_id)
    order = await session.get(Order, invoice.order_id)
    buyer_email = None
    if order is not None:
        user = await session.get(User, order.user_id)
        buyer_email = _readable_email(crypto, user)

    pdf = invoice_documents.render_invoice_pdf(
        invoice=invoice,
        items=items,
        # The tenant is the supplier — this platform is multi-tenant and
        # each one issues its own invoices under its own name.
        supplier_name=tenant.name,
        buyer_email=buyer_email,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="invoice-{invoice.number}.pdf"'},
    )


def _readable_email(crypto: CryptoBox, user: User | None) -> str | None:
    """A buyer whose address is under a rotated key still gets a valid
    invoice — the document is about the transaction, and the address is
    a courtesy line on it (docs/STATUS.md §10)."""
    if user is None:
        return None
    try:
        return crypto.decrypt(user.email_encrypted)
    except Exception:
        return None


def _csv(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
