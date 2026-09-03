"""Payment-gateway webhooks (03 §5.7) — the one deliberate exception to
"the browser is the only caller, everything else is internal." A gateway's
own server calls this, not a browser, so none of the BFF/CORS reasoning
(`apps/web/app/api/bff/[...path]/route.ts`'s own docstring) applies here;
this stays a plain top-level API route, unauthenticated by design (a
webhook carries no user session) but signature-validated in its place.

No `TenantDep` — a webhook arrives with no `X-Tenant-Host` a browser would
carry, so tenant resolution can't happen the normal way
(`core/tenancy.py`). `resolve_payment_tenant` (migration `0024`) is the
one narrow, SECURITY DEFINER-backed exception that looks a tenant up from
the payload's own referenced payment id, following the exact precedent
`0005` already set for the maintenance-worker functions.

Order of operations matters and is deliberate: resolve tenant → verify
signature → confirm with the provider (the live anti-forgery round-trip)
→ only then trust anything else in the payload. Persist a
`PaymentWebhook` row regardless of outcome — even a rejected notification
is worth a reconciliation record — and always return `200` once
persisted, per spec: "retry storms are worse than late processing."
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select, text

from src.core.db import tenant_session
from src.core.deps import CryptoDep, PaymentProviderDep, SettingsDep
from src.core.ids import uuid7
from src.core.logging import get_logger
from src.models.audit import AuditAction
from src.models.commerce import Order, Payment, PaymentWebhook
from src.services import audit
from src.services import orders as orders_service
from src.services.orders import OrderError

log = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _already_processed(session: Any, *, provider: str, event_id: str) -> bool:
    existing = await session.execute(
        select(PaymentWebhook.id).where(
            PaymentWebhook.provider == provider, PaymentWebhook.provider_event_id == event_id
        )
    )
    return existing.first() is not None


@router.post("/payfast", status_code=status.HTTP_200_OK, response_model=None)
async def payfast_webhook(
    request: Request,
    crypto: CryptoDep,
    settings: SettingsDep,
    provider: PaymentProviderDep,
) -> Response:
    raw_body = await request.body()
    form = await request.form()
    # dict comprehension over multi_items(), not dict(form) — preserves
    # the exact order Payfast sent fields in, which the ITN signature
    # check has to reconstruct field-for-field (payfast.py's own
    # docstring, uncertainty #2).
    fields: dict[str, str] = {k: str(v) for k, v in form.multi_items()}

    payment_id_raw = fields.get("m_payment_id", "")
    try:
        payment_id = uuid.UUID(payment_id_raw)
    except ValueError:
        # Not even a real UUID — nothing to resolve a tenant from, and
        # nothing genuinely TTLI's own gateway would ever send. Logged,
        # not audited (no tenant to audit it under), still 200 (per spec,
        # a malformed/unrecognised notification isn't worth a retry
        # storm either).
        log.warning("payfast_webhook_unresolvable_payment_id", raw=payment_id_raw[:64])
        return Response(status_code=status.HTTP_200_OK)

    async with tenant_session(None) as lookup_session:
        tenant_id = (
            await lookup_session.execute(
                text("SELECT resolve_payment_tenant(:p)"), {"p": payment_id}
            )
        ).scalar_one_or_none()

    if tenant_id is None:
        log.warning("payfast_webhook_unknown_payment", payment_id=str(payment_id))
        return Response(status_code=status.HTTP_200_OK)

    async with tenant_session(tenant_id) as session:
        if not provider.verify_signature(fields):
            await audit.record(
                session,
                tenant_id=tenant_id,
                action=AuditAction.PAYMENT_WEBHOOK_REJECTED,
                entity_type="payment",
                entity_id=payment_id,
                after={"reason": "invalid_signature", "provider": provider.name},
            )
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)

        if not await provider.confirm_with_provider(fields):
            await audit.record(
                session,
                tenant_id=tenant_id,
                action=AuditAction.PAYMENT_WEBHOOK_REJECTED,
                entity_type="payment",
                entity_id=payment_id,
                after={"reason": "provider_confirmation_failed", "provider": provider.name},
            )
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)

        event = provider.parse_webhook(fields)

        if await _already_processed(session, provider=provider.name, event_id=event.event_id):
            return Response(status_code=status.HTTP_200_OK)

        payment = await session.get(Payment, event.payment_id)
        if payment is None or payment.tenant_id != tenant_id:
            log.error("payfast_webhook_payment_mismatch", payment_id=str(event.payment_id))
            return Response(status_code=status.HTTP_200_OK)

        order = await session.get(Order, payment.order_id)
        if order is None:
            log.error("payfast_webhook_order_missing", payment_id=str(payment.id))
            return Response(status_code=status.HTTP_200_OK)

        # Amount is never trusted from the payload alone (03 §5.7's own
        # server-side-validation requirement) — checked against what this
        # system itself recorded as owed, the same discipline
        # services/orders.py::create_order already applies to prices.
        amount_matches = event.amount == payment.amount

        if event.succeeded and amount_matches:
            try:
                await orders_service.fulfil_card_payment(
                    session,
                    tenant_id=tenant_id,
                    order=order,
                    payment=payment,
                    supplier_vat_number=settings.supplier_vat_number or None,
                )
            except OrderError:
                # fable5.1_review.md H-4: `checkout_card` (orders.py) makes
                # a fresh `Payment` per checkout attempt, so a buyer who
                # pays twice (two tabs, a retried checkout) has two
                # genuinely-charged `Payment` rows for the same order. The
                # first ITN fulfils it; this second, later-arriving one is
                # a real confirmed charge for an order that is no longer
                # `pending_payment` — `fulfil_card_payment` raises for
                # exactly that (its own status guard, or `_fulfil_order`'s
                # locked recheck under true concurrency). Left unhandled,
                # that exception used to propagate out of `tenant_session`
                # before the `PaymentWebhook` row below was ever written —
                # no audit trail, no 200, Payfast retries the same ITN
                # forever. Persisted and flagged instead: this order's
                # `pending_payment` -> `fulfilled` transition already
                # happened via the correct payment; this row records the
                # duplicate charge that still needs a human to reconcile
                # (via `list_pending_payments`'-style tooling, or the raw
                # `payments` table) rather than losing it silently.
                # `order.status` reflects the fresh, lock-refreshed read
                # `_fulfil_order` did before raising — checked instead of
                # blindly trusting every `OrderError` here is this
                # specific "someone else already got there first" case,
                # so a genuine fulfilment bug (a missing product link, a
                # deleted buyer) still surfaces instead of being silently
                # relabelled a duplicate.
                if order.status == "pending_payment":
                    raise
                payment.status = "duplicate_charge"
                log.error(
                    "payfast_webhook_order_already_fulfilled",
                    payment_id=str(payment.id),
                    order_id=str(order.id),
                    order_status=order.status,
                )
                await audit.record(
                    session,
                    tenant_id=tenant_id,
                    action=AuditAction.PAYMENT_WEBHOOK_DUPLICATE_CHARGE,
                    entity_type="payment",
                    entity_id=payment.id,
                    after={
                        "order_id": str(order.id),
                        "order_status": order.status,
                        "provider": provider.name,
                    },
                )
        else:
            payment.status = "failed" if not event.succeeded else "amount_mismatch"
            if not amount_matches:
                log.error(
                    "payfast_webhook_amount_mismatch",
                    payment_id=str(payment.id),
                    expected=str(payment.amount),
                    received=str(event.amount),
                )

        session.add(
            PaymentWebhook(
                id=uuid7(),
                tenant_id=tenant_id,
                payment_id=payment.id,
                provider=provider.name,
                provider_event_id=event.event_id,
                raw_payload_encrypted=crypto.encrypt(raw_body.decode("utf-8", errors="replace")),
            )
        )

    return Response(status_code=status.HTTP_200_OK)


__all__ = ["router"]
