"""Order creation and the EFT purchase path (01 §4.1, 01 §4.3 workflow 4,
REQ-PAY-03).

Prices are resolved server-side from `prices` — a client submits a
`price_id` and quantity, never a raw amount (03 §5.1). Every line's tax is
resolved through `services/tax.py`; an order that would need a tax
treatment that isn't configured (an international customer, pending 01
§1.4 #2) is refused at creation, not created half-priced.

Entitlements are granted only on the transition to `fulfilled`, in the same
transaction as invoice issuance and the ledger entries recording both —
never before (02 §6.2, 01 §4.1).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError
from src.core.ids import uuid7
from src.models.commerce import Invoice, Order, OrderItem, Payment, Price, Product, TaxRule
from src.models.user import User
from src.services import enrolment as enrolment_service
from src.services import entitlements, invoicing, ledger, tax


class OrderError(AppError):
    """A refusal in the order flow — a bad state transition, an unknown or
    mismatched price, or a product that isn't sellable right now."""

    code = "ORDER_ERROR"


@dataclass(frozen=True, slots=True)
class OrderLineRequest:
    price_id: uuid.UUID
    quantity: int


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def create_order(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    currency: str,
    customer_type: str,
    lines: list[OrderLineRequest],
    organisation_id: uuid.UUID | None = None,
) -> Order:
    if not lines:
        raise OrderError("An order needs at least one line item.")

    # Resolve and validate every line before writing anything: get_session()
    # commits whatever an AppError leaves flushed (deliberately, for auth
    # bookkeeping — core/deps.py), so raising partway through a loop that
    # had already added rows would leave an orphaned empty order behind.
    resolved: list[tuple[Product, Price, TaxRule, Decimal, Decimal, Decimal]] = []
    for line in lines:
        if line.quantity < 1:
            raise OrderError("Quantity must be at least 1.")
        price = await session.get(Price, line.price_id)
        if price is None or price.tenant_id != tenant_id:
            raise OrderError(f"No such price: {line.price_id}")
        if price.currency != currency:
            raise OrderError(f"Price {line.price_id} is not priced in {currency!r}.")
        product = await session.get(Product, price.product_id)
        if product is None or not product.is_active:
            raise OrderError(f"Product for price {line.price_id} is not available.")

        tax_rule = await tax.resolve(
            session, tenant_id=tenant_id, customer_type=customer_type, product_kind=product.kind
        )

        line_subtotal = _quantize(price.unit_amount * line.quantity)
        line_tax = _quantize(line_subtotal * tax_rule.rate)
        line_total = (
            line_subtotal + line_tax if price.tax_behaviour == "exclusive" else line_subtotal
        )
        resolved.append((product, price, tax_rule, line_subtotal, line_tax, line_total))

    order = Order(
        id=uuid7(),
        tenant_id=tenant_id,
        user_id=user_id,
        organisation_id=organisation_id,
        status="draft",
        currency=currency,
        subtotal=Decimal("0"),
        tax_total=Decimal("0"),
        grand_total=Decimal("0"),
    )
    session.add(order)
    await session.flush()

    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line, (product, price, tax_rule, line_subtotal, line_tax, line_total) in zip(
        lines, resolved, strict=True
    ):
        session.add(
            OrderItem(
                id=uuid7(),
                tenant_id=tenant_id,
                order_id=order.id,
                product_id=product.id,
                price_id=price.id,
                tax_rule_id=tax_rule.id,
                quantity=line.quantity,
                unit_amount=price.unit_amount,
                tax_amount=line_tax,
                line_total=line_total,
            )
        )
        subtotal += line_subtotal
        tax_total += line_tax

    order.subtotal = subtotal
    order.tax_total = tax_total
    order.grand_total = subtotal + tax_total
    order.status = "pending_payment"
    await session.flush()
    return order


def _generate_payment_reference(order_id: uuid.UUID) -> str:
    # Short, unique and legible enough for a learner to quote on an EFT —
    # derived from the order's own id, so the DB's unique index is the only
    # uniqueness check needed, not a separate generate-and-retry loop.
    # Sliced from hex[12:22], not hex[:10]: a UUID7's first 12 hex chars are
    # its millisecond timestamp (core/ids.py), so two orders created in the
    # same millisecond would otherwise get an identical reference — this
    # slice starts right after that shared prefix, in the random portion.
    return f"EFT-{order_id.hex[12:22].upper()}"


async def checkout_eft(session: AsyncSession, *, tenant_id: uuid.UUID, order: Order) -> Payment:
    if order.status != "pending_payment":
        raise OrderError(f"Order is {order.status!r}, not ready for EFT checkout.")

    order.payment_reference = _generate_payment_reference(order.id)
    order.status = "eft_pending_proof"
    payment = Payment(
        id=uuid7(),
        tenant_id=tenant_id,
        order_id=order.id,
        provider="eft",
        amount=order.grand_total,
        currency=order.currency,
        status="pending",
    )
    session.add(payment)
    await session.flush()
    return payment


async def submit_proof(
    session: AsyncSession, *, order: Order, payment: Payment, proof_object_key: str
) -> None:
    # eft_rejected is allowed here too: "eft_rejected returns to
    # eft_pending_proof on resubmission" (01 §4.1) — a rejected order can
    # try again with new proof.
    if order.status not in ("eft_pending_proof", "eft_rejected"):
        raise OrderError(f"Order is {order.status!r}; no proof is expected right now.")
    payment.proof_object_key = proof_object_key
    payment.status = "pending"
    payment.rejection_reason = None
    order.status = "eft_pending_approval"
    await session.flush()


async def checkout_po(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    po_number: str,
    po_document_key: str,
) -> Payment:
    """01 §4.3 workflow 5's "PO number and document captured" step — a
    purchase order arrives as a document from the start, unlike EFT
    proof which only exists after a bank transfer, so this is one call
    straight to `po_pending_approval` rather than two steps."""
    if order.status != "pending_payment":
        raise OrderError(f"Order is {order.status!r}, not ready for PO checkout.")
    if not po_number.strip():
        raise OrderError("A purchase order number is required.")

    order.po_number = po_number
    order.po_document_key = po_document_key
    order.status = "po_pending_approval"
    payment = Payment(
        id=uuid7(),
        tenant_id=tenant_id,
        order_id=order.id,
        provider="po",
        amount=order.grand_total,
        currency=order.currency,
        status="pending",
    )
    session.add(payment)
    await session.flush()
    return payment


async def _fulfil_order(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    payment: Payment,
    approved_by_user_id: uuid.UUID,
    supplier_vat_number: str | None,
) -> Invoice:
    """Shared by `approve_eft` and `approve_po` — invoice issuance,
    entitlement/enrolment granting and the ledger entries that record
    both, identical regardless of which payment method got the order
    here. The two callers differ only in which status they're leaving
    (`eft_pending_approval` vs `po_pending_approval`) and what payment
    metadata that implies — never in what fulfilment itself means.

    `order.organisation_id` set (02 §4.7) means this order bought seat
    capacity, not a direct entitlement for `order.user_id` — the buyer
    is the organisation admin who placed the order, not necessarily a
    learner. Seats are assigned to specific employees afterward via
    `services/organisations.py::assign_seat`, drawing from the pool this
    creates."""
    payment.status = "manually_approved"
    payment.approved_by_user_id = approved_by_user_id
    payment.approved_at = datetime.now(UTC)

    invoice = await invoicing.issue(
        session, tenant_id=tenant_id, order=order, supplier_vat_number=supplier_vat_number
    )

    items = (
        await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars()
    for item in items:
        product = await session.get(Product, item.product_id)
        if product is None:
            raise OrderError("Order references a product that no longer exists.")

        # Product.kind is "course" for everything sold so far — target_id
        # resolves to the real course now (Phase 4), not the product's own
        # id used as a stand-in before courses existed (see git history on
        # services/entitlements.py's docstring).
        if product.kind == "course":
            if product.course_id is None:
                raise OrderError(
                    f"Product {product.slug!r} is a course product with no linked course; "
                    "cannot grant entitlement."
                )
            target_id = product.course_id
        else:
            target_id = product.id

        if order.organisation_id is not None:
            # The seat pool itself — no user_id, drawn from later by
            # assign_seat (0016's migration docstring).
            entitlement = await entitlements.grant(
                session,
                tenant_id=tenant_id,
                user_id=None,
                source_order_id=order.id,
                kind=product.kind,
                target_id=target_id,
                quantity=item.quantity,
            )
            entitlement.organisation_id = order.organisation_id
            continue

        entitlement = await entitlements.grant(
            session,
            tenant_id=tenant_id,
            user_id=order.user_id,
            source_order_id=order.id,
            kind=product.kind,
            target_id=target_id,
            quantity=item.quantity,
        )

        if product.kind == "course":
            await enrolment_service.get_or_create_enrolment(
                session,
                tenant_id=tenant_id,
                user_id=order.user_id,
                course_id=target_id,
                entitlement_id=entitlement.id,
            )

    order.status = "fulfilled"
    await session.flush()

    await ledger.record(
        session,
        tenant_id=tenant_id,
        entity_type="payment",
        entity_id=payment.id,
        entry_type=ledger.EntryType.PAYMENT_RECEIVED,
        amount=payment.amount,
        vat_amount=order.tax_total,
        currency=order.currency,
        reference=order.payment_reference,
    )
    await ledger.record(
        session,
        tenant_id=tenant_id,
        entity_type="invoice",
        entity_id=invoice.id,
        entry_type=ledger.EntryType.INVOICE_ISSUED,
        amount=invoice.grand_total,
        vat_amount=invoice.tax_total,
        currency=invoice.currency,
        reference=invoice.number,
        created_by=approved_by_user_id,
    )
    return invoice


async def approve_eft(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    payment: Payment,
    approved_by_user_id: uuid.UUID,
    supplier_vat_number: str | None,
) -> Invoice:
    if order.status != "eft_pending_approval":
        raise OrderError(f"Order is {order.status!r}, not awaiting EFT approval.")
    return await _fulfil_order(
        session,
        tenant_id=tenant_id,
        order=order,
        payment=payment,
        approved_by_user_id=approved_by_user_id,
        supplier_vat_number=supplier_vat_number,
    )


async def approve_po(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    payment: Payment,
    approved_by_user_id: uuid.UUID,
    supplier_vat_number: str | None,
) -> Invoice:
    if order.status != "po_pending_approval":
        raise OrderError(f"Order is {order.status!r}, not awaiting PO approval.")
    return await _fulfil_order(
        session,
        tenant_id=tenant_id,
        order=order,
        payment=payment,
        approved_by_user_id=approved_by_user_id,
        supplier_vat_number=supplier_vat_number,
    )


async def reject_eft(session: AsyncSession, *, order: Order, payment: Payment, reason: str) -> None:
    if order.status != "eft_pending_approval":
        raise OrderError(f"Order is {order.status!r}, not awaiting EFT approval.")
    payment.status = "eft_rejected"
    payment.rejection_reason = reason
    order.status = "eft_rejected"
    await session.flush()


async def reject_po(session: AsyncSession, *, order: Order, payment: Payment, reason: str) -> None:
    # No po_rejected state exists in order_status (0009) — unlike EFT,
    # a PO doesn't get resubmitted with corrected proof; "cancelled" is
    # the real terminal state a rejected PO lands in.
    if order.status != "po_pending_approval":
        raise OrderError(f"Order is {order.status!r}, not awaiting PO approval.")
    payment.status = "po_rejected"
    payment.rejection_reason = reason
    order.status = "cancelled"
    await session.flush()


@dataclass(frozen=True, slots=True)
class PendingPayment:
    payment_id: uuid.UUID
    order_id: uuid.UUID
    buyer_email: str
    amount: Decimal
    currency: str
    payment_reference: str | None
    provider: str
    po_number: str | None
    proof_uploaded: bool
    created_at: datetime


async def list_pending_payments(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[PendingPayment], int]:
    """The finance queue (REQ-PAY-03): EFT and PO payments awaiting a
    human decision — proof uploaded or PO document captured. There is
    no automated approval path for either.
    """
    base = (
        select(Payment, Order, User)
        .join(Order, Order.id == Payment.order_id)
        .join(User, User.id == Order.user_id)
        .where(
            Order.tenant_id == tenant_id,
            Order.status.in_(("eft_pending_approval", "po_pending_approval")),
        )
    )
    total = len((await session.execute(base)).all())

    rows = (
        await session.execute(base.order_by(Payment.created_at.desc()).limit(limit).offset(offset))
    ).all()
    items = [
        PendingPayment(
            payment_id=payment.id,
            order_id=order.id,
            buyer_email=crypto.decrypt(user.email_encrypted),
            amount=payment.amount,
            currency=payment.currency,
            payment_reference=order.payment_reference,
            provider=payment.provider,
            po_number=order.po_number,
            proof_uploaded=payment.proof_object_key is not None
            or order.po_document_key is not None,
            created_at=payment.created_at,
        )
        for payment, order, user in rows
    ]
    return items, total


__all__ = [
    "OrderError",
    "OrderLineRequest",
    "PendingPayment",
    "approve_eft",
    "approve_po",
    "checkout_eft",
    "checkout_po",
    "create_order",
    "list_pending_payments",
    "reject_eft",
    "reject_po",
    "submit_proof",
]
