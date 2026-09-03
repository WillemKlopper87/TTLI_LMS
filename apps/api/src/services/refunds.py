"""Refunds and credit notes (02 §6.3/6.4, 01 §1.4's Phase 3 remainder).

Full-refund only, deliberately — the same "one complete vertical slice"
narrowing Phase 3 sprint 1 already applied to EFT-only checkout. A
partial, line-item refund/credit note is real future scope this module
doesn't cover; a `fulfilled` order is refunded for its entire
`grand_total` or not at all.

Like EFT approval, this records that a human moved money outside the
system — there is still no live payment gateway to call a refund API on
(01 §1.4's Phase 0 outstanding list) — it does not move money itself.
`process_refund` always writes a `CreditNote` (the accounting correction
to the invoice) and a `Refund` (the payment-event record) together in one
transaction: a refund without its credit note is a real invoice nobody
corrected; a credit note without its refund fact claims money moved that
this system never recorded moving. Both, or neither.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError
from src.core.ids import uuid7
from src.models.audit import AuditAction
from src.models.commerce import CreditNote, Entitlement, Invoice, Order, Payment, Refund
from src.services import audit, invoicing, ledger

CREDIT_NOTE_SERIES = "CN"


class RefundError(AppError):
    """A refusal in the refund flow — the order isn't in a refundable
    state, or has no invoice to credit."""

    code = "REFUND_ERROR"


async def issue_credit_note(
    session: AsyncSession, *, tenant_id: uuid.UUID, invoice: Invoice, reason: str
) -> CreditNote:
    """Credits an invoice's full total. Reuses `invoicing.next_sequence`
    under a separate `"CN"` series, so credit notes and invoices count
    independently — a gap in one series says nothing about the other,
    which is exactly what SARS needs each series to guarantee on its own.
    """
    sequence = await invoicing.next_sequence(
        session, tenant_id=tenant_id, series=CREDIT_NOTE_SERIES
    )
    number = f"{CREDIT_NOTE_SERIES}-{sequence:06d}"

    credit_note = CreditNote(
        id=uuid7(),
        tenant_id=tenant_id,
        invoice_id=invoice.id,
        number=number,
        series=CREDIT_NOTE_SERIES,
        sequence=sequence,
        currency=invoice.currency,
        amount=invoice.grand_total,
        tax_amount=invoice.tax_total,
        reason=reason,
    )
    session.add(credit_note)
    invoice.status = "credited"
    await session.flush()
    return credit_note


async def process_refund(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    reason: str,
    processed_by_user_id: uuid.UUID,
) -> tuple[Refund, CreditNote]:
    """Refund a fulfilled order in full: issue its credit note, record the
    refund fact, revoke the entitlements this order granted, and mark the
    order refunded — all in one transaction.

    Only `fulfilled` orders qualify. `eft_pending_approval`/
    `po_pending_approval` orders that were never approved have
    `reject_eft`/`reject_po` for exactly that case (no money was ever
    recorded received, so there is nothing to refund); refunding here
    would double up on that already-correct refusal path rather than
    replace it.

    fable5.1_review.md H-3: like `services/orders.py::_fulfil_order`'s
    H-2 fix, the caller (`routers/orders.py::refund_order`) loads `order`
    with a plain `session.get` and no lock. Two concurrent refund
    requests for the same order (two `Idempotency-Key`s, or a retried
    request racing the first) could both pass an unlocked `order.status
    != "fulfilled"` check before either commits, and both would then
    issue a credit note, record a refund and revoke entitlements a
    second time — `credit_notes`/`refunds` are append-only (module
    docstring), so a duplicate can't be cleaned up after the fact the way
    a mistaken row elsewhere could be. This locked re-check, mirroring
    `_fulfil_order`'s `with_for_update()` idiom, is the actual guard; the
    router's own check is just an optimistic fast path.
    """
    order = (
        await session.execute(
            select(Order)
            .where(Order.id == order.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if order.status != "fulfilled":
        raise RefundError(f"Order is {order.status!r}, not fulfilled — nothing to refund.")

    payment = (
        (
            await session.execute(
                select(Payment)
                .where(Payment.order_id == order.id, Payment.tenant_id == tenant_id)
                .order_by(Payment.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if payment is None:
        raise RefundError("Order has no payment on record.")

    invoice = (
        await session.execute(
            select(Invoice).where(Invoice.order_id == order.id, Invoice.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise RefundError("Order has no invoice to credit.")
    if invoice.status == "credited":
        raise RefundError("This order has already been refunded.")

    credit_note = await issue_credit_note(
        session, tenant_id=tenant_id, invoice=invoice, reason=reason
    )

    refund = Refund(
        id=uuid7(),
        tenant_id=tenant_id,
        order_id=order.id,
        payment_id=payment.id,
        credit_note_id=credit_note.id,
        amount=invoice.grand_total,
        currency=invoice.currency,
        reason=reason,
        processed_by_user_id=processed_by_user_id,
    )
    session.add(refund)

    # Cuts access immediately via has_valid_course_entitlement's existing
    # revoked_at check — the same mechanism a lapsed subscription already
    # relies on (services/subscriptions.py), not a new access-control path.
    # Scoped to this order's own entitlements only: a seat-pool order's
    # pool entitlement is revoked here, but reassigning/revoking
    # individually-assigned seats stays organisations.py::revoke_seat's
    # job (a real, separate boundary — not silently short-circuited here).
    entitlements = (
        await session.execute(
            select(Entitlement).where(
                Entitlement.tenant_id == tenant_id,
                Entitlement.source_order_id == order.id,
                Entitlement.revoked_at.is_(None),
            )
        )
    ).scalars()
    now = datetime.now(UTC)
    for entitlement in entitlements:
        entitlement.revoked_at = now

    order.status = "refunded"
    await session.flush()

    await ledger.record(
        session,
        tenant_id=tenant_id,
        entity_type="credit_note",
        entity_id=credit_note.id,
        entry_type=ledger.EntryType.CREDIT_NOTE_ISSUED,
        amount=credit_note.amount,
        vat_amount=credit_note.tax_amount,
        currency=credit_note.currency,
        reference=credit_note.number,
        created_by=processed_by_user_id,
    )
    await ledger.record(
        session,
        tenant_id=tenant_id,
        entity_type="refund",
        entity_id=refund.id,
        entry_type=ledger.EntryType.REFUND_ISSUED,
        amount=refund.amount,
        vat_amount=invoice.tax_total,
        currency=refund.currency,
        reference=order.payment_reference,
        created_by=processed_by_user_id,
    )
    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.REFUND_ISSUED,
        actor_user_id=processed_by_user_id,
        entity_type="order",
        entity_id=order.id,
        after={
            "refund_id": str(refund.id),
            "credit_note_number": credit_note.number,
            "currency": order.currency,
            "amount": str(refund.amount),
            "reason": reason,
        },
    )
    return refund, credit_note


__all__ = ["CREDIT_NOTE_SERIES", "RefundError", "issue_credit_note", "process_refund"]
