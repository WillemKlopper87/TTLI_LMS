"""`services/payments/payfast.py` — pure logic only, no network, no DB.

This is the honestly-testable half of the adapter: signature generation
and validation are self-consistent (compute the same way on both sides,
so correctness can be verified without a live Payfast account), and
`initiate_checkout` refuses outright with no credentials configured,
which needs no network call to prove either. `confirm_with_provider` —
the one live server-to-server round-trip — is not exercised here at all;
see `tests/test_webhooks.py` for how the router around it is tested
instead, with that one call substituted.
"""

from __future__ import annotations

import hashlib
import urllib.parse
import uuid
from decimal import Decimal

import pytest
from src.models.commerce import Order
from src.services.payments.payfast import PayfastProvider, PaymentProviderUnavailable


def _order(**overrides: object) -> Order:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "status": "pending_payment",
        "currency": "ZAR",
        "grand_total": Decimal("575.00"),
    }
    defaults.update(overrides)
    return Order(**defaults)  # type: ignore[arg-type]


TEST_PASSPHRASE = "jt7NOE43FZPn"


@pytest.fixture
def provider() -> PayfastProvider:
    return PayfastProvider(
        merchant_id="10000100",
        merchant_key="46f0cd694581a",
        passphrase=TEST_PASSPHRASE,
        sandbox=True,
    )


async def test_initiate_checkout_refuses_with_no_credentials() -> None:
    unconfigured = PayfastProvider(merchant_id="", merchant_key="", passphrase="", sandbox=True)
    with pytest.raises(PaymentProviderUnavailable):
        await unconfigured.initiate_checkout(
            order=_order(),
            payment_id=uuid.uuid4(),
            return_url="https://example.com/return",
            cancel_url="https://example.com/cancel",
            notify_url="https://example.com/notify",
            buyer_email="buyer@example.com",
        )


async def test_initiate_checkout_signs_the_redirect(provider: PayfastProvider) -> None:
    redirect = await provider.initiate_checkout(
        order=_order(),
        payment_id=uuid.uuid4(),
        return_url="https://example.com/return",
        cancel_url="https://example.com/cancel",
        notify_url="https://example.com/notify",
        buyer_email="buyer@example.com",
    )
    assert redirect.action_url == "https://sandbox.payfast.co.za/eng/process"
    assert redirect.fields["merchant_id"] == "10000100"
    assert redirect.fields["amount"] == "575.00"
    assert len(redirect.fields["signature"]) == 32  # md5 hex digest length
    # The signature must actually be a function of the fields — changing
    # the amount without re-signing must not still validate.
    assert provider.verify_signature(redirect.fields)
    tampered = dict(redirect.fields)
    tampered["amount"] = "0.01"
    assert not provider.verify_signature(tampered)


async def test_production_host_when_not_sandbox() -> None:
    live = PayfastProvider(merchant_id="x", merchant_key="y", passphrase="", sandbox=False)
    redirect = await live.initiate_checkout(
        order=_order(),
        payment_id=uuid.uuid4(),
        return_url="https://example.com/return",
        cancel_url="https://example.com/cancel",
        notify_url="https://example.com/notify",
        buyer_email="buyer@example.com",
    )
    assert redirect.action_url == "https://www.payfast.co.za/eng/process"


def test_verify_signature_accepts_a_self_consistent_itn(provider: PayfastProvider) -> None:
    """A synthetic ITN this test signs itself, the same way a real one
    from Payfast would arrive: fields in receipt order, `signature` last.
    """
    fields = {
        "m_payment_id": str(uuid.uuid4()),
        "pf_payment_id": "1104856",
        "payment_status": "COMPLETE",
        "amount_gross": "575.00",
    }
    # Sign it exactly the way the provider itself would when *validating*
    # — reusing the private helper would defeat the point of the test, so
    # this recomputes independently via the public verify path: sign,
    # then check verify_signature agrees.
    query = "&".join(f"{k}={urllib.parse.quote_plus(v)}" for k, v in fields.items())
    query += f"&passphrase={urllib.parse.quote_plus(TEST_PASSPHRASE)}"
    fields["signature"] = hashlib.md5(query.encode()).hexdigest()  # noqa: S324

    assert provider.verify_signature(fields)


def test_verify_signature_rejects_wrong_passphrase() -> None:
    signer = PayfastProvider(merchant_id="x", merchant_key="y", passphrase="right", sandbox=True)
    checker = PayfastProvider(merchant_id="x", merchant_key="y", passphrase="wrong", sandbox=True)
    fields = {"m_payment_id": "abc", "payment_status": "COMPLETE"}

    query = "&".join(f"{k}={urllib.parse.quote_plus(v)}" for k, v in fields.items())
    query += "&passphrase=right"
    fields["signature"] = hashlib.md5(query.encode()).hexdigest()  # noqa: S324

    assert signer.verify_signature(fields)
    assert not checker.verify_signature(fields)


def test_verify_signature_rejects_missing_signature(provider: PayfastProvider) -> None:
    assert not provider.verify_signature({"m_payment_id": "abc"})


def test_parse_webhook_reads_documented_fields(provider: PayfastProvider) -> None:
    payment_id = uuid.uuid4()
    event = provider.parse_webhook(
        {
            "m_payment_id": str(payment_id),
            "pf_payment_id": "1104856",
            "payment_status": "COMPLETE",
            "amount_gross": "575.00",
        }
    )
    assert event.payment_id == payment_id
    assert event.event_id == "1104856"
    assert event.succeeded is True
    assert event.amount == Decimal("575.00")
    assert event.currency == "ZAR"  # Payfast never settles in anything else


def test_parse_webhook_not_complete_is_not_succeeded(provider: PayfastProvider) -> None:
    event = provider.parse_webhook(
        {
            "m_payment_id": str(uuid.uuid4()),
            "pf_payment_id": "1104857",
            "payment_status": "CANCELLED",
            "amount_gross": "575.00",
        }
    )
    assert event.succeeded is False
