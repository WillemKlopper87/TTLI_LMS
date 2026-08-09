"""Orders and the EFT purchase path (03 §5.1/5.3/5.4/5.6, REQ-PAY-03).

Buyer-facing actions (create, checkout, upload proof) are gated on the
caller owning the order — this is a learner acting on their own purchase,
not an admin action. Approval and rejection are gated on `payment:approve`
instead — that is finance acting on someone else's order, and REQ-PAY-03
requires a human in that loop; there is no automated approval path.

Card checkout (Payfast/Netcash) and PO capture are not built here — see
`alembic/versions/0009_commerce_foundation.py`'s docstring for why this
migration only builds the EFT path.

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

from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy import select

from src.core.deps import PrincipalDep, SessionDep, SettingsDep, StorageDep
from src.core.errors import AppError, Forbidden, NotFound
from src.models.commerce import Order, OrderItem, Payment
from src.schemas.commerce import (
    CreateOrderRequest,
    EftCheckoutResponse,
    InvoiceResponse,
    OrderItemResponse,
    OrderResponse,
    RejectPaymentRequest,
)
from src.services import orders as orders_service
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


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: CreateOrderRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> OrderResponse:
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
    key = f"{principal.tenant_id}/{order.id}/{uuid.uuid4().hex}-{file.filename or 'proof'}"
    await storage.ensure_container(Container.USER_UPLOADS)
    await storage.upload_object(Container.USER_UPLOADS, key, data, content_type=file.content_type)
    # Virus scanning before the file is readable by anyone (04 §2,
    # REQ-BYPASS-08) is a documented control this sprint does not implement
    # — no scanning engine exists in this project yet. Tracked in
    # STATUS.md as a gap, not silently skipped.
    await orders_service.submit_proof(session, order=order, payment=payment, proof_object_key=key)


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

    invoice = await orders_service.approve_eft(
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

    await orders_service.reject_eft(session, order=order, payment=payment, reason=body.reason)


__all__ = ["router"]
