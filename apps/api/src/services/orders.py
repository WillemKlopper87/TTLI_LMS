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

from cryptography.exceptions import InvalidTag
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError
from src.core.ids import uuid7
from src.core.logging import get_logger
from src.models.audit import AuditAction
from src.models.commerce import Invoice, Order, OrderItem, Payment, Price, Product, TaxRule
from src.models.learning_path import PathEnrolment
from src.models.user import User
from src.services import audit, entitlements, invoicing, ledger, push, tax
from src.services import enrolment as enrolment_service
from src.services import learning_paths as paths_service
from src.services import subscriptions as subscriptions_service
from src.services.payments.base import CheckoutRedirect, PaymentProvider

log = get_logger(__name__)


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


@dataclass(frozen=True, slots=True)
class ResolvedLine:
    """What `price_order_lines` needs to price one line — already resolved
    against the DB (`Price`/`TaxRule`), carrying nothing further to look
    up. `tax_behaviour` is `Price.tax_behaviour` ("inclusive" | "exclusive")."""

    unit_amount: Decimal
    quantity: int
    tax_rate: Decimal
    tax_behaviour: str


@dataclass(frozen=True, slots=True)
class LinePricing:
    subtotal: Decimal
    tax: Decimal
    total: Decimal


@dataclass(frozen=True, slots=True)
class OrderPricing:
    lines: tuple[LinePricing, ...]
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal


def price_order_lines(lines: list[ResolvedLine]) -> OrderPricing:
    """The pure per-line pricing/tax math extracted out of `create_order`'s
    resolve-and-validate loop (TTLI_Audit_Report_2026-09-02.md M5) — the DB
    reads that resolve each line's `Price`/`TaxRule` stay exactly where
    they were; only the arithmetic moved, so it can be unit-tested without
    a session. Order of `lines` in, order of `.lines` out — callers zip
    back against their own per-line context (`OrderItem` creation) by
    position, same as `create_order` already did with `zip(..., strict=True)`.

    `tax_behaviour == "exclusive"`: `unit_amount` excludes tax — tax is
    added on top (`net * rate`), and the line's total is `net + tax`.
    `tax_behaviour == "inclusive"`: `unit_amount` is the advertised,
    all-in price — the customer must never be charged more than that
    (fable5.1_review.md H-1), so tax is *extracted* from it
    (`gross * rate / (1 + rate)`), not added a second time, and the
    line's total stays the advertised gross. `line_subtotal` is the
    ex-tax net either way (what changes is how it's derived), so
    `subtotal + tax_total == grand_total` holds uniformly for both
    behaviours — `create_order`/invoicing rely on exactly that identity.
    """
    priced: list[LinePricing] = []
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for line in lines:
        if line.tax_behaviour == "inclusive":
            gross = _quantize(line.unit_amount * line.quantity)
            line_tax = _quantize(gross * line.tax_rate / (Decimal("1") + line.tax_rate))
            # Subtraction of two already-quantized 2dp Decimals is exact,
            # so line_subtotal + line_tax == gross always, regardless of
            # how line_tax happened to round — the buyer's line total
            # never drifts from the advertised inclusive price.
            line_subtotal = gross - line_tax
        else:
            line_subtotal = _quantize(line.unit_amount * line.quantity)
            line_tax = _quantize(line_subtotal * line.tax_rate)
        line_total = line_subtotal + line_tax
        priced.append(LinePricing(subtotal=line_subtotal, tax=line_tax, total=line_total))
        subtotal += line_subtotal
        tax_total += line_tax
    return OrderPricing(
        lines=tuple(priced),
        subtotal=subtotal,
        tax_total=tax_total,
        grand_total=subtotal + tax_total,
    )


async def create_order(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    currency: str,
    customer_type: str,
    lines: list[OrderLineRequest],
    organisation_id: uuid.UUID | None = None,
    subscription_id: uuid.UUID | None = None,
) -> Order:
    if not lines:
        raise OrderError("An order needs at least one line item.")

    # Resolve and validate every line before writing anything: get_session()
    # commits whatever an AppError leaves flushed (deliberately, for auth
    # bookkeeping — core/deps.py), so raising partway through a loop that
    # had already added rows would leave an orphaned empty order behind.
    resolved: list[tuple[Product, Price, TaxRule]] = []
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
        if organisation_id is not None and product.kind != "course":
            # Seat-pool fulfilment (the branch below, and
            # organisations.py::assign_seat downstream of it) only knows
            # how to draw a course-kind entitlement from a pool — a path
            # or subscription product routed through an organisation
            # order would take the buyer's money with no way to ever
            # deliver it (a path pool entitlement nothing can assign) or
            # crash mid-approval (a subscription order with no
            # subscription_id, since only routers/subscriptions.py's own
            # flow ever sets that). Refused here, before any money moves,
            # rather than discovered at fulfilment time.
            raise OrderError(
                f"'{product.name}' can't be bought for an organisation yet — "
                "only individual courses support seat purchases."
            )

        tax_rule = await tax.resolve(
            session, tenant_id=tenant_id, customer_type=customer_type, product_kind=product.kind
        )
        resolved.append((product, price, tax_rule))

    order = Order(
        id=uuid7(),
        tenant_id=tenant_id,
        user_id=user_id,
        organisation_id=organisation_id,
        subscription_id=subscription_id,
        status="draft",
        currency=currency,
        subtotal=Decimal("0"),
        tax_total=Decimal("0"),
        grand_total=Decimal("0"),
    )
    session.add(order)
    await session.flush()

    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=price.unit_amount,
                quantity=line.quantity,
                tax_rate=tax_rule.rate,
                tax_behaviour=price.tax_behaviour,
            )
            for line, (_product, price, tax_rule) in zip(lines, resolved, strict=True)
        ]
    )
    for line, (product, price, tax_rule), line_pricing in zip(
        lines, resolved, pricing.lines, strict=True
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
                tax_amount=line_pricing.tax,
                line_total=line_pricing.total,
            )
        )

    order.subtotal = pricing.subtotal
    order.tax_total = pricing.tax_total
    order.grand_total = pricing.grand_total
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


async def checkout_card(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    provider: PaymentProvider,
    return_url: str,
    cancel_url: str,
    notify_url: str,
) -> tuple[Payment, CheckoutRedirect]:
    """03 §5.2. Deliberately leaves `order.status` at `pending_payment`
    rather than introducing a new intermediate enum value — unlike EFT/PO,
    there is nothing for the buyer or an admin to *do* between "redirected
    to the gateway" and the webhook resolving it, so a distinct status
    would describe a state nobody ever needs to see or act on. A failed
    or abandoned attempt leaves nothing committed; the buyer can simply
    check out again, which creates a fresh `Payment` row.
    """
    if order.status != "pending_payment":
        raise OrderError(f"Order is {order.status!r}, not ready for card checkout.")

    buyer = await session.get(User, order.user_id)
    if buyer is None:
        raise OrderError("Order references a buyer that no longer exists.")
    try:
        buyer_email = crypto.decrypt(buyer.email_encrypted)
    except InvalidTag as exc:
        # Same class of gap list_pending_payments already tolerates for
        # finance's queue — a row encrypted under a since-rotated key.
        # Checkout can't silently substitute a placeholder the way a
        # read-only queue can, since this email is going to the gateway
        # as the buyer's own identity — refuse loudly instead.
        raise OrderError("This account's stored email could not be read. Contact support.") from exc

    payment = Payment(
        id=uuid7(),
        tenant_id=tenant_id,
        order_id=order.id,
        provider="card",
        amount=order.grand_total,
        currency=order.currency,
        status="pending",
    )
    session.add(payment)
    await session.flush()

    redirect = await provider.initiate_checkout(
        order=order,
        payment_id=payment.id,
        return_url=return_url,
        cancel_url=cancel_url,
        notify_url=notify_url,
        buyer_email=buyer_email,
    )
    return payment, redirect


async def _fulfil_path_purchase(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source_order_id: uuid.UUID,
    learning_path_id: uuid.UUID,
    path_entitlement_id: uuid.UUID,
) -> None:
    """The path entitlement alone isn't enough to unlock its member
    courses: `entitlements.has_valid_course_entitlement` and `enrolment_
    service.get_own_enrolment`'s live re-check are both hardcoded to
    `kind == "course"` (deliberately narrow, not a bug — see `entitlements
    .py`'s own docstring on `target_id` being polymorphic). So a path
    purchase grants one `course`-kind entitlement and one `Enrolment`
    per member course, in `learning_path_courses.position` order, on top
    of the path entitlement `_fulfil_order` already granted — the same
    "one purchase, several entitlement rows for different purposes"
    shape `services/organisations.py::assign_seat` already uses for a
    pool entitlement plus a per-employee one.

    `PathEnrolment` is get-or-create, not a plain insert: a learner who
    already holds this path (e.g. a second purchase after the first
    lapsed) must not violate `path_enrolments`' one-row-per-user-per-path
    unique index, same reasoning `enrolment_service.get_or_create_
    enrolment`'s own docstring gives for a course."""
    members = await paths_service.list_path_courses(
        session, learning_path_id=learning_path_id, tenant_id=tenant_id
    )
    for _member, course in members:
        course_entitlement = await entitlements.grant(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            source_order_id=source_order_id,
            kind="course",
            target_id=course.id,
        )
        await enrolment_service.get_or_create_enrolment(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            course_id=course.id,
            entitlement_id=course_entitlement.id,
        )

    existing = (
        await session.execute(
            select(PathEnrolment).where(
                PathEnrolment.tenant_id == tenant_id,
                PathEnrolment.user_id == user_id,
                PathEnrolment.learning_path_id == learning_path_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            PathEnrolment(
                id=uuid7(),
                tenant_id=tenant_id,
                user_id=user_id,
                learning_path_id=learning_path_id,
                entitlement_id=path_entitlement_id,
            )
        )
        await session.flush()


async def _fulfil_order(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    payment: Payment,
    approved_by_user_id: uuid.UUID | None,
    payment_status: str,
    supplier_vat_number: str | None,
) -> Invoice:
    """Shared by `approve_eft`, `approve_po` and `fulfil_card_payment` —
    invoice issuance, entitlement/enrolment granting and the ledger
    entries that record both, identical regardless of which payment
    method got the order here. The three callers differ only in which
    status they're leaving and what payment metadata that implies — never
    in what fulfilment itself means.

    `approved_by_user_id` is nullable specifically for the card path: a
    gateway webhook confirms the payment, not a human, so there is no
    finance user to record — `payment_status` carries the real distinction
    ("manually_approved" vs "complete") instead of overloading who
    approved it to also mean how.

    `order.organisation_id` set (02 §4.7) means this order bought seat
    capacity, not a direct entitlement for `order.user_id` — the buyer
    is the organisation admin who placed the order, not necessarily a
    learner. Seats are assigned to specific employees afterward via
    `services/organisations.py::assign_seat`, drawing from the pool this
    creates."""
    payment.status = payment_status
    payment.approved_by_user_id = approved_by_user_id
    payment.approved_at = datetime.now(UTC)

    invoice = await invoicing.issue(
        session, tenant_id=tenant_id, order=order, supplier_vat_number=supplier_vat_number
    )

    # REQ-LEAD-07: a guest who pays keeps the same email and the same
    # account — this just lifts the guest flag rather than creating a
    # second user, so nothing needs "carrying forward" (a guest's own
    # preview access is view-only and never touches an Enrolment; see
    # services/guest_access.py). Without this, guest_expires_at keeps
    # ticking after a real purchase and eventually locks the now-paying
    # customer out of the very account they bought with.
    buyer = await session.get(User, order.user_id)
    if buyer is not None and buyer.is_guest:
        buyer.is_guest = False
        buyer.guest_expires_at = None

    items = (
        await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars()
    for item in items:
        product = await session.get(Product, item.product_id)
        if product is None:
            raise OrderError("Order references a product that no longer exists.")

        if product.kind == "subscription":
            # A subscription period funds itself entirely differently from
            # a course/seat purchase — no single Entitlement/Enrolment
            # pair, but one per bundled course, each expiring at the new
            # period end (services/subscriptions.py). Nothing below this
            # branch applies to it.
            await subscriptions_service.fulfil_subscription_order(
                session, tenant_id=tenant_id, order=order, product=product
            )
            continue

        # Product.kind is "course"/"path"/"workshop_credit" for
        # everything sold so far — target_id resolves to the real
        # course/path/workshop (Phase 4/P5, P7 phase 4), not the
        # product's own id used as a stand-in before courses existed
        # (see git history on services/entitlements.py's docstring).
        if product.kind == "course":
            if product.course_id is None:
                raise OrderError(
                    f"Product {product.slug!r} is a course product with no linked course; "
                    "cannot grant entitlement."
                )
            target_id = product.course_id
        elif product.kind == "path":
            if product.learning_path_id is None:
                raise OrderError(
                    f"Product {product.slug!r} is a path product with no linked learning "
                    "path; cannot grant entitlement."
                )
            target_id = product.learning_path_id
        elif product.kind == "workshop_credit":
            if product.workshop_id is None:
                raise OrderError(
                    f"Product {product.slug!r} is a workshop-credit product with no linked "
                    "workshop; cannot grant entitlement."
                )
            target_id = product.workshop_id
        else:
            target_id = product.id

        if order.organisation_id is not None:
            # The seat pool itself — no user_id, drawn from later by
            # assign_seat (0016's migration docstring). Always a
            # course-kind product here: create_order refuses any other
            # kind for an organisation order (organisations.py::
            # assign_seat and its pool queries only know "course",
            # so a path or subscription pool entitlement would sit
            # here undeliverable — see docs/research/p5-review-
            # findings.md F1). Granting the entitlement here, with no
            # user to enrol yet, is still correct for a course: real
            # enrolment happens later, per employee, in assign_seat.
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
        elif product.kind == "path":
            await _fulfil_path_purchase(
                session,
                tenant_id=tenant_id,
                user_id=order.user_id,
                source_order_id=order.id,
                learning_path_id=target_id,
                path_entitlement_id=entitlement.id,
            )
        # workshop_credit deliberately has no branch here (P7 phase 4):
        # the entitlement just granted, with quantity=item.quantity, is
        # the entire fulfilment — a credit is a balance, not an
        # enrolment. services/workshops.py::book_session finds and
        # decrements it later, at the moment a learner actually books.

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

    # order.organisation_id set means this bought seat capacity, not a
    # direct entitlement (docstring above) — order.user_id is then the
    # org admin who placed the order, still the right person to tell
    # "your payment was approved," not a learner who hasn't been
    # assigned a seat yet.
    await push.notify_user(
        session,
        tenant_id=tenant_id,
        user_id=order.user_id,
        title="Payment approved",
        body=(
            f"Your payment of {order.currency} {order.grand_total} was approved — "
            "access is now available."
        ),
        url="/learn",
    )
    # Pass B: money moving on a human decision is the first thing a
    # compliance reviewer looks for, and until now none of it was
    # logged. `approved_by_user_id` is None on the card path (a gateway
    # webhook confirmed it, not a person) — recorded as such rather than
    # attributed to nobody in particular.
    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.PAYMENT_APPROVED,
        actor_user_id=approved_by_user_id,
        entity_type="order",
        entity_id=order.id,
        after={
            "payment_id": str(payment.id),
            "payment_status": payment_status,
            "currency": order.currency,
            "grand_total": str(order.grand_total),
            "invoice_number": invoice.number,
        },
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
        payment_status="manually_approved",
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
        payment_status="manually_approved",
        supplier_vat_number=supplier_vat_number,
    )


async def fulfil_card_payment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    order: Order,
    payment: Payment,
    supplier_vat_number: str | None,
) -> Invoice:
    """Called from `routers/webhooks.py` once a provider notification is
    signature-verified, source-confirmed, and amount-checked — the
    gateway is the authority here, unlike EFT/PO, so there is no separate
    human-approval step the way REQ-PAY-03 requires for those two.
    `approved_by_user_id` stays `None`: nobody approved this, the payment
    provider confirmed it.
    """
    if order.status != "pending_payment":
        raise OrderError(f"Order is {order.status!r}, not awaiting card payment.")
    return await _fulfil_order(
        session,
        tenant_id=tenant_id,
        order=order,
        payment=payment,
        approved_by_user_id=None,
        payment_status="complete",
        supplier_vat_number=supplier_vat_number,
    )


async def reject_eft(session: AsyncSession, *, order: Order, payment: Payment, reason: str) -> None:
    if order.status != "eft_pending_approval":
        raise OrderError(f"Order is {order.status!r}, not awaiting EFT approval.")
    payment.status = "eft_rejected"
    payment.rejection_reason = reason
    order.status = "eft_rejected"
    await session.flush()
    await audit.record(
        session,
        tenant_id=order.tenant_id,
        action=AuditAction.PAYMENT_REJECTED,
        entity_type="order",
        entity_id=order.id,
        after={"payment_id": str(payment.id), "reason": reason},
    )
    await push.notify_user(
        session,
        tenant_id=order.tenant_id,
        user_id=order.user_id,
        title="Payment not approved",
        body=f"Your payment could not be approved: {reason}",
        url="/checkout",
    )


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
    await push.notify_user(
        session,
        tenant_id=order.tenant_id,
        user_id=order.user_id,
        title="Payment not approved",
        body=f"Your payment could not be approved: {reason}",
        url="/checkout",
    )


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
    subscription_id: uuid.UUID | None


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
    items = []
    for payment, order, user in rows:
        try:
            buyer_email = crypto.decrypt(user.email_encrypted)
        except InvalidTag:
            # A row encrypted under a since-rotated key can't crash the
            # whole finance queue over one bad email — surfaced instead of
            # silently dropped, since finance still needs to act on the
            # payment itself.
            log.error("buyer_email_undecryptable", order_id=str(order.id), user_id=str(user.id))
            buyer_email = "(email unreadable — key rotated since this order was placed)"
        items.append(
            PendingPayment(
                payment_id=payment.id,
                order_id=order.id,
                buyer_email=buyer_email,
                amount=payment.amount,
                currency=payment.currency,
                payment_reference=order.payment_reference,
                provider=payment.provider,
                po_number=order.po_number,
                proof_uploaded=payment.proof_object_key is not None
                or order.po_document_key is not None,
                created_at=payment.created_at,
                subscription_id=order.subscription_id,
            )
        )
    return items, total


__all__ = [
    "LinePricing",
    "OrderError",
    "OrderLineRequest",
    "OrderPricing",
    "PendingPayment",
    "ResolvedLine",
    "approve_eft",
    "approve_po",
    "checkout_eft",
    "checkout_po",
    "create_order",
    "list_pending_payments",
    "price_order_lines",
    "reject_eft",
    "reject_po",
    "submit_proof",
]
