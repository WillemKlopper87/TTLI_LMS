"""Payfast (03 §5.2/5.7) — written to Payfast's documented API, **never
executed against a live Payfast account**. There is no sandbox
merchant_id/merchant_key on file (01 §1.4's Phase 0 outstanding list);
`settings.payfast_merchant_id` empty is what keeps card checkout
correctly *off* rather than attempting one with invented credentials
(`config.py`'s own comment). Everything below is real code, built the
same way `services/media/{ffmpeg,transcoder}.py` were ported from
`Streaming_Server` — read carefully, implemented faithfully — but that
precedent was verified against a real ffmpeg binary; this one has no
real gateway to verify against yet. **Re-verify every detail here
against a live sandbox before this is trusted with a real payment.**

Two specific, documented uncertainties worth knowing before touching this
file, found while researching it rather than assumed:

1. **Checkout-signature field order is genuinely disputed even in
   Payfast's own materials.** Older official documentation examples used
   alphabetical field order; newer guidance says submission order (the
   order fields appear in the form) instead — both versions are still
   live on different pages, and at least one careful third-party
   implementation write-up explicitly called the official worked example
   "flawed." This module follows Payfast's own documented *grouping*
   (merchant details → buyer details → transaction details) for the
   outgoing checkout signature, which is the more consistently described
   approach across current sources — but this is exactly the kind of
   thing that must be confirmed against a real sandbox response before
   going live, not trusted from research alone.
2. **ITN (webhook) signature validation is the more settled half** — the
   consistent, cross-source description is: reconstruct the query string
   from the fields *in the order Payfast sent them* (not a fixed order we
   choose), excluding `signature` itself, append the passphrase, MD5 hash,
   lowercase hex. That's what `verify_signature` below does.

Payfast recommends **four** ITN checks, not just the signature — source
validation (this module does it via the live `confirm_with_provider`
round-trip, not a static IP allowlist, since Payfast's own published IP
ranges are documented to drift and third parties have had to repeatedly
ask hosts to update stale allowlists), signature validation, and
server-side amount verification (done by the caller — `routers/
webhooks.py` — against the order's own recorded total, never trusted from
the payload alone).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Mapping
from decimal import Decimal

import httpx

from src.core.errors import AppError
from src.models.commerce import Order
from src.services.payments.base import CheckoutRedirect, WebhookResult

# Once-off-payment fields only — no subscription/tokenization fields,
# since nothing in this project bills a card on a recurring schedule
# (subscription renewals are EFT/PO-funded, services/subscriptions.py's
# own docstring). Grouped per Payfast's documented field categories;
# see the module docstring's uncertainty #1 before reordering this.
_CHECKOUT_FIELD_ORDER = (
    "merchant_id",
    "merchant_key",
    "return_url",
    "cancel_url",
    "notify_url",
    "name_first",
    "email_address",
    "m_payment_id",
    "amount",
    "item_name",
)


class PaymentProviderUnavailable(AppError):
    code = "PAYMENT_PROVIDER_UNAVAILABLE"
    status_code = 503


def _signature_string(fields: Mapping[str, str], *, passphrase: str) -> str:
    """The one routine both checkout-signing and ITN-validation share:
    URL-encode each non-empty value (`quote_plus` — spaces become `+`,
    matching Payfast's own documented encoding, not `%20`), join with
    `&` in the *given* mapping's iteration order, append the passphrase.
    Callers are responsible for supplying fields in the order that
    matters for their case (see the two docstring uncertainties above) —
    this function makes no ordering decision itself.
    """
    import urllib.parse

    parts = [
        f"{key}={urllib.parse.quote_plus(str(value).strip())}"
        for key, value in fields.items()
        if key != "signature" and value not in (None, "")
    ]
    query = "&".join(parts)
    if passphrase:
        query += f"&passphrase={urllib.parse.quote_plus(passphrase)}"
    return query


class PayfastProvider:
    name = "payfast"

    def __init__(
        self, *, merchant_id: str, merchant_key: str, passphrase: str, sandbox: bool
    ) -> None:
        self._merchant_id = merchant_id
        self._merchant_key = merchant_key
        self._passphrase = passphrase
        self._sandbox = sandbox

    @property
    def _host(self) -> str:
        return "sandbox.payfast.co.za" if self._sandbox else "www.payfast.co.za"

    async def initiate_checkout(
        self,
        *,
        order: Order,
        payment_id: uuid.UUID,
        return_url: str,
        cancel_url: str,
        notify_url: str,
        buyer_email: str,
    ) -> CheckoutRedirect:
        if not self._merchant_id or not self._merchant_key:
            raise PaymentProviderUnavailable("Card checkout is not configured for this deployment.")

        fields: dict[str, str] = {}
        for key in _CHECKOUT_FIELD_ORDER:
            fields[key] = {
                "merchant_id": self._merchant_id,
                "merchant_key": self._merchant_key,
                "return_url": return_url,
                "cancel_url": cancel_url,
                "notify_url": notify_url,
                "name_first": "",
                "email_address": buyer_email,
                "m_payment_id": str(payment_id),
                "amount": f"{order.grand_total:.2f}",
                "item_name": f"Order {order.id}"[:100],  # Payfast's own field-length limit
            }[key]

        # MD5 is Payfast's own mandated signature algorithm, not a choice
        # made here — every current source on their checkout/ITN process
        # agrees on this much, however much the field-order details are
        # disputed (module docstring). Not used for anything this
        # project controls the design of.
        signature = hashlib.md5(  # noqa: S324
            _signature_string(fields, passphrase=self._passphrase).encode()
        ).hexdigest()
        fields["signature"] = signature
        return CheckoutRedirect(action_url=f"https://{self._host}/eng/process", fields=fields)

    def verify_signature(self, fields: Mapping[str, str]) -> bool:
        received = fields.get("signature")
        if not received:
            return False
        # Field order here is the ITN's own received order — the caller
        # (routers/webhooks.py) is responsible for passing an
        # order-preserving mapping (Starlette's FormData already is one).
        computed = hashlib.md5(  # noqa: S324 - Payfast's own algorithm, see above
            _signature_string(fields, passphrase=self._passphrase).encode()
        ).hexdigest()
        return hmac.compare_digest(computed, received.lower())

    async def confirm_with_provider(self, fields: Mapping[str, str]) -> bool:
        """The live server-to-server round-trip Payfast documents as the
        real anti-forgery check — a leaked passphrase can forge a valid
        signature, but not a response only Payfast's own server can give.
        Never executed against a real Payfast account (see module
        docstring); a network failure here is treated as *not confirmed*
        — fail closed, the same posture services/antivirus.py takes on an
        unreachable ClamAV, because the failure mode is money, not
        convenience.
        """
        body = "&".join(f"{k}={v}" for k, v in fields.items() if k != "signature")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"https://{self._host}/eng/query/validate",
                    content=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.HTTPError:
            return False
        return resp.text.strip() == "VALID"

    def parse_webhook(self, fields: Mapping[str, str]) -> WebhookResult:
        return WebhookResult(
            event_id=fields["pf_payment_id"],
            payment_id=uuid.UUID(fields["m_payment_id"]),
            succeeded=fields.get("payment_status") == "COMPLETE",
            amount=Decimal(fields["amount_gross"]),
            # Payfast settles in ZAR only (confirmed during the
            # international-payments research this sprint followed) —
            # never the order's own currency for a non-ZAR order, which
            # is exactly why that research recommended a Merchant-of-
            # Record path for international buyers rather than routing
            # them through this adapter.
            currency="ZAR",
        )


__all__ = ["PayfastProvider", "PaymentProviderUnavailable"]
