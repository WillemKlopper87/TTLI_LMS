"""The provider-agnostic contract every card gateway implements.

Four operations, deliberately split rather than one "handle_webhook"
method, because they have different trust levels and different testability:

- `initiate_checkout` needs no incoming data to trust — it's us building a
  redirect.
- `verify_signature` is a pure function over the received fields — fully
  unit-testable with no network call, and the first line of defence
  against a forged notification.
- `confirm_with_provider` is the live, server-to-server round-trip back to
  the gateway that Payfast's own documentation recommends *in addition to*
  signature checking, not instead of it — a leaked passphrase forges a
  valid signature too, so signature-only trust is real but incomplete.
  This is the one operation that cannot be exercised without a live
  provider account (see `payfast.py`'s own docstring).
- `parse_webhook` turns the provider's own field names into the shape
  `routers/webhooks.py` actually needs, so that router never imports a
  provider-specific field name.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from src.models.commerce import Order


@dataclass(frozen=True, slots=True)
class CheckoutRedirect:
    """What the buyer's browser needs to reach the gateway's hosted
    checkout page. `fields` are submitted as a standard form POST — no
    card data ever passes through TTLI's own servers (REQ-PAY-06)."""

    action_url: str
    fields: dict[str, str]


@dataclass(frozen=True, slots=True)
class WebhookResult:
    """A provider notification, normalised. `event_id` is the provider's
    own transaction identifier — not TTLI's own payment/order id — because
    idempotency (03 §1.6) has to key on "has this specific provider event
    been processed before," and only the provider can tell us that."""

    event_id: str
    payment_id: uuid.UUID
    succeeded: bool
    amount: Decimal
    currency: str


class PaymentProvider(Protocol):
    name: str

    async def initiate_checkout(
        self,
        *,
        order: Order,
        payment_id: uuid.UUID,
        return_url: str,
        cancel_url: str,
        notify_url: str,
        buyer_email: str,
    ) -> CheckoutRedirect: ...

    def verify_signature(self, fields: Mapping[str, str]) -> bool:
        """Pure — no I/O. False on anything malformed, never raises."""
        ...

    async def confirm_with_provider(self, fields: Mapping[str, str]) -> bool:
        """The live anti-forgery round-trip. A network failure here must
        be treated as *not confirmed* (fail closed) — see the ClamAV
        precedent in services/antivirus.py for why "the dependency is
        down" means refuse, not degrade gracefully, wherever the failure
        mode is money or bypassed access rather than convenience."""
        ...

    def parse_webhook(self, fields: Mapping[str, str]) -> WebhookResult: ...


__all__ = ["CheckoutRedirect", "PaymentProvider", "WebhookResult"]
