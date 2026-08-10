"""Orders and the EFT/PO purchase paths (03 §5.1/5.3/5.4/5.6, REQ-PAY-03,
0016's PO checkout).

Buyer-facing actions (create, checkout, upload proof) are gated on the
caller owning the order — this is a learner (or, for a seat purchase,
an organisation admin buying on the org's behalf) acting on their own
purchase, not an admin action. Approval and rejection are gated on
`payment:approve` instead — that is finance acting on someone else's
order, and REQ-PAY-03 requires a human in that loop; there is no
automated approval path, for either payment method.

Card checkout (Payfast/Netcash) is still not built here — blocked on
live sandbox credentials (01 §1.4's Phase 0 outstanding list), not a
design gap the way PO checkout was.

03 §1.6 requires `Idempotency-Key` handling on `POST /orders` and
`POST /payments/*` — deferred this sprint (tracked in STATUS.md), since it
matters most for the webhook/gateway retries that come with card checkout,
which isn't built yet either. It is not a silent gap in the meantime: every
`services/orders.py` transition checks the order/payment is in the expected
state before acting, so a genuine double-submission (a retried approve,
a doubled proof upload) is refused with a 400, not silently re-executed —
that is what stops a duplicate invoice or entitlement, even though the
refusal isn't full Idempotency-Key replay semantics (returning the original
response rather than an error).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from sqlalchemy import select

from src.core.deps import CryptoDep, PrincipalDep, SessionDep, SettingsDep, StorageDep, TenantDep
from src.core.errors import AppError, Forbidden, NotFound, ServiceUnavailable
from src.models.commerce import Order, OrderItem, Payment
from src.schemas.commerce import (
    CreateOrderRequest,
    EftCheckoutResponse,
    InvoiceResponse,
    OrderItemResponse,
    OrderResponse,
    PendingPaymentsPage,
    PendingPaymentSummary,
    PoCheckoutResponse,
    PriceSummary,
    ProductsPage,
    ProductSummary,
    RejectPaymentRequest,
)
from src.services import antivirus, catalogue
from src.services import orders as orders_service
from src.services import organisations as organisations_service
from src.services.storage import Container

router = APIRouter(tags=["commerce"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


async def _get_order(session: SessionDep, order_id: str) -> Order:
    order = await session.get(Order, _parse_uuid(order_id))
    if order is None:
        raise NotFound("No such order.")
    return order


async def _get_own_order(session: SessionDep, principal: PrincipalDep, order_id: str) -> Order:
    order = await _get_order(session, order_id)
    if order.user_id != principal.user_id:
        raise Forbidden("You do not have access to this order.")
    return order


async def _order_response(session: SessionDep, order: Order) -> OrderResponse:
    items = (
        await session.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars()
    return OrderResponse(
        id=str(order.id),
        status=order.status,
        currency=order.currency,
        subtotal=order.subtotal,
        tax_total=order.tax_total,
        grand_total=order.grand_total,
        payment_reference=order.payment_reference,
        po_number=order.po_number,
        organisation_id=str(order.organisation_id) if order.organisation_id else None,
        items=[
            OrderItemResponse(
                product_id=str(item.product_id),
                quantity=item.quantity,
                unit_amount=item.unit_amount,
                tax_amount=item.tax_amount,
                line_total=item.line_total,
            )
            for item in items
        ],
    )


@router.get("/products", response_model=ProductsPage, summary="The public product catalogue")
async def list_products(session: SessionDep, tenant: TenantDep) -> ProductsPage:
    products = await catalogue.list_active_products(session, tenant_id=tenant.id)
    return ProductsPage(
        items=[
            ProductSummary(
                id=str(p.id),
                slug=p.slug,
                name=p.name,
                description=p.description,
                kind=p.kind,
                prices=[
                    PriceSummary(
                        id=str(price.id),
                        currency=price.currency,
                        unit_amount=price.unit_amount,
                        tax_behaviour=price.tax_behaviour,
                    )
                    for price in p.prices
                ],
            )
            for p in products
        ]
    )


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: CreateOrderRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> OrderResponse:
    organisation_id = None
    if body.organisation_id is not None:
        organisation_id = _parse_uuid(body.organisation_id)
        # Only that organisation's own admin can spend its money — the
        # same ownership discipline every other buyer-facing endpoint in
        # this file uses, just scoped to an org instead of a single user.
        await organisations_service.require_admin(
            session,
            tenant_id=principal.tenant_id,
            organisation_id=organisation_id,
            user_id=principal.user_id,
        )

    lines = [
        orders_service.OrderLineRequest(price_id=_parse_uuid(line.price_id), quantity=line.quantity)
        for line in body.lines
    ]
    order = await orders_service.create_order(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        currency=body.currency.upper(),
        customer_type=body.customer_type,
        lines=lines,
        organisation_id=organisation_id,
    )
    return await _order_response(session, order)


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, principal: PrincipalDep, session: SessionDep) -> OrderResponse:
    order = await _get_own_order(session, principal, order_id)
    return await _order_response(session, order)


@router.post("/orders/{order_id}/checkout/eft", response_model=EftCheckoutResponse)
async def checkout_eft(
    order_id: str, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> EftCheckoutResponse:
    order = await _get_own_order(session, principal, order_id)
    payment = await orders_service.checkout_eft(session, tenant_id=principal.tenant_id, order=order)
    return EftCheckoutResponse(
        payment_id=str(payment.id),
        payment_reference=order.payment_reference or "",
        bank_name=settings.eft_bank_name,
        account_name=settings.eft_account_name,
        account_number=settings.eft_account_number,
        branch_code=settings.eft_branch_code,
        amount=payment.amount,
        currency=payment.currency,
    )


@router.post("/orders/{order_id}/checkout/po", response_model=PoCheckoutResponse)
async def checkout_po(
    order_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    po_number: str = Form(...),
    file: UploadFile = File(...),
) -> PoCheckoutResponse:
    """01 §4.3 workflow 5: the PO number and its document arrive together
    — unlike EFT proof, which can only exist after a bank transfer, a
    purchase order document exists from the moment it's raised."""
    order = await _get_own_order(session, principal, order_id)
    data = await file.read()

    # Same fail-closed virus-scanning rule as EFT proof (REQ-BYPASS-08) —
    # a PO document is exactly the kind of upload it protects against.
    try:
        result = await antivirus.scan(data, settings=settings)
    except antivirus.ScanUnavailable as exc:
        raise ServiceUnavailable("The virus scanner is unavailable. Try again shortly.") from exc
    if not result.clean:
        raise AppError(
            "That file was rejected by the virus scanner and was not stored.",
            {"signature": result.signature},
        )

    key = f"{principal.tenant_id}/{order.id}/{uuid.uuid4().hex}-{file.filename or 'po'}"
    await storage.ensure_container(Container.USER_UPLOADS)
    await storage.upload_object(Container.USER_UPLOADS, key, data, content_type=file.content_type)

    payment = await orders_service.checkout_po(
        session,
        tenant_id=principal.tenant_id,
        order=order,
        po_number=po_number,
        po_document_key=key,
    )
    return PoCheckoutResponse(
        payment_id=str(payment.id),
        po_number=order.po_number or "",
        amount=payment.amount,
        currency=payment.currency,
    )


@router.post(
    "/orders/{order_id}/payment-proof",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def upload_payment_proof(
    order_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> None:
    order = await _get_own_order(session, principal, order_id)
    payment = (
        (
            await session.execute(
                select(Payment)
                .where(Payment.order_id == order.id)
                .order_by(Payment.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if payment is None:
        raise AppError("No payment awaiting proof for this order.")

    data = await file.read()

    # Virus scanning before the file is readable by anyone (04 §3,
    # REQ-BYPASS-08) — scanned before it ever reaches storage, and both an
    # infection and an unreachable scanner refuse the upload. Failing open
    # here (accepting on a scanner outage) is exactly the gap this control
    # exists to close.
    try:
        result = await antivirus.scan(data, settings=settings)
    except antivirus.ScanUnavailable as exc:
        raise ServiceUnavailable("The virus scanner is unavailable. Try again shortly.") from exc
    if not result.clean:
        raise AppError(
            "That file was rejected by the virus scanner and was not stored.",
            {"signature": result.signature},
        )

    key = f"{principal.tenant_id}/{order.id}/{uuid.uuid4().hex}-{file.filename or 'proof'}"
    await storage.ensure_container(Container.USER_UPLOADS)
    await storage.upload_object(Container.USER_UPLOADS, key, data, content_type=file.content_type)
    await orders_service.submit_proof(session, order=order, payment=payment, proof_object_key=key)


@router.get("/payments", response_model=PendingPaymentsPage, summary="The finance approval queue")
async def list_pending_payments(
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PendingPaymentsPage:
    principal.require("payment:approve")
    items, total = await orders_service.list_pending_payments(
        session, crypto, tenant_id=principal.tenant_id, limit=limit, offset=offset
    )
    return PendingPaymentsPage(
        items=[
            PendingPaymentSummary(
                payment_id=str(row.payment_id),
                order_id=str(row.order_id),
                buyer_email=row.buyer_email,
                amount=row.amount,
                currency=row.currency,
                payment_reference=row.payment_reference,
                provider=row.provider,
                po_number=row.po_number,
                proof_uploaded=row.proof_uploaded,
                created_at=row.created_at,
            )
            for row in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/payments/{payment_id}/approve", response_model=InvoiceResponse)
async def approve_payment(
    payment_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> InvoiceResponse:
    principal.require("payment:approve")
    payment = await session.get(Payment, _parse_uuid(payment_id))
    if payment is None:
        raise NotFound("No such payment.")
    order = await _get_order(session, str(payment.order_id))

    approve_fn = (
        orders_service.approve_po if payment.provider == "po" else orders_service.approve_eft
    )
    invoice = await approve_fn(
        session,
        tenant_id=principal.tenant_id,
        order=order,
        payment=payment,
        approved_by_user_id=principal.user_id,
        supplier_vat_number=settings.supplier_vat_number or None,
    )
    return InvoiceResponse(
        id=str(invoice.id),
        number=invoice.number,
        status=invoice.status,
        issued_at=invoice.issued_at,
        currency=invoice.currency,
        subtotal=invoice.subtotal,
        tax_total=invoice.tax_total,
        grand_total=invoice.grand_total,
    )


@router.post(
    "/payments/{payment_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def reject_payment(
    payment_id: str,
    body: RejectPaymentRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> None:
    principal.require("payment:approve")
    payment = await session.get(Payment, _parse_uuid(payment_id))
    if payment is None:
        raise NotFound("No such payment.")
    order = await _get_order(session, str(payment.order_id))

    reject_fn = orders_service.reject_po if payment.provider == "po" else orders_service.reject_eft
    await reject_fn(session, order=order, payment=payment, reason=body.reason)


__all__ = ["router"]
