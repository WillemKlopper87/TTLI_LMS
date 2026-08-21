"""Reading invoices back, the tax-invoice PDF, and the accounting
exports (`routers/invoices.py`, backlog P6).

Invoicing was write-only until this pass: gapless, ledger-backed, and
unreadable by the buyer it was issued to. These tests cover who may read
what, that the PDF is a real PDF of the right invoice, and that the CSV
exports carry the columns an accountant reconciles with.
"""

from __future__ import annotations

import socket
import uuid
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from src.core.db import dispose_engine, init_engine
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.models.rbac import RoleAssignment
from src.services import identity

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"
PASSWORD = "correct horse battery staple 9!"


def _redis_reachable(url: str) -> bool:
    parsed = urlparse(url)
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((parsed.hostname or "localhost", parsed.port or 6379))
        return True
    except OSError:
        return False
    finally:
        sock.close()


@pytest.fixture
async def client(settings, database_url):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip("no Redis on the configured REDIS_URL")
    init_engine(settings)
    redis = init_redis(settings)
    await redis.flushdb()
    await init_queue(settings)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.headers["X-Tenant-Host"] = TENANT_HOST
        yield c
    await dispose_engine()
    await dispose_redis()
    await dispose_queue()


def _unique_email() -> str:
    return f"inv-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str((await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one())


async def _login(client, tenant_session_factory, crypto, *, tenant_id, role: str | None) -> str:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role))
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _buy_one(client, tenant_session_factory, crypto, *, tenant_id) -> tuple[str, str]:
    """A real fulfilled purchase: order, EFT checkout, proof, finance
    approval. Returns (buyer_token, invoice_id) — the only way to get a
    genuine invoice, since nothing in this codebase mints one directly."""
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)
    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )

    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {buyer}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]

    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer}"},
    )
    assert checkout.status_code == 200, checkout.text
    payment_id = checkout.json()["payment_id"]

    proof = await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer}"},
        files={"file": ("proof.pdf", b"%PDF-fake-proof", "application/pdf")},
    )
    assert proof.status_code == 204, proof.text

    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200, approve.text
    return buyer, approve.json()["id"]


async def test_a_buyer_reads_their_own_invoice_without_any_permission(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    """An invoice is a document about that person's own money. Needing a
    permission to see it would be the wrong shape."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    buyer, invoice_id = await _buy_one(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    headers = {"Authorization": f"Bearer {buyer}"}

    listing = await client.get("/api/v1/invoices", headers=headers)
    assert listing.status_code == 200, listing.text
    numbers = [row["id"] for row in listing.json()["items"]]
    assert invoice_id in numbers

    detail = await client.get(f"/api/v1/invoices/{invoice_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["number"].startswith("INV-")
    assert body["items"], "an invoice without lines is not an invoice"
    # The lines must reconcile with the header, or the document lies.
    assert round(sum(float(i["line_total"]) for i in body["items"]), 2) == round(
        float(body["grand_total"]), 2
    )


async def test_one_buyer_cannot_read_another_buyers_invoice(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    _owner, invoice_id = await _buy_one(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    stranger = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    resp = await client.get(
        f"/api/v1/invoices/{invoice_id}", headers={"Authorization": f"Bearer {stranger}"}
    )
    assert resp.status_code == 403

    # And a stranger's listing is their own, which is empty.
    listing = await client.get("/api/v1/invoices", headers={"Authorization": f"Bearer {stranger}"})
    assert listing.status_code == 200
    assert invoice_id not in [row["id"] for row in listing.json()["items"]]

    # Asking for the whole tenant without order:view is refused outright.
    wide = await client.get(
        "/api/v1/invoices?mine=false", headers={"Authorization": f"Bearer {stranger}"}
    )
    assert wide.status_code == 403


async def test_the_pdf_is_a_real_pdf_for_that_invoice(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    buyer, invoice_id = await _buy_one(client, tenant_session_factory, crypto, tenant_id=tenant_id)
    headers = {"Authorization": f"Bearer {buyer}"}

    detail = await client.get(f"/api/v1/invoices/{invoice_id}", headers=headers)
    number = detail.json()["number"]

    pdf = await client.get(f"/api/v1/invoices/{invoice_id}/pdf", headers=headers)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    # A real PDF, not an error page with the wrong content type.
    assert pdf.content.startswith(b"%PDF-")
    assert number in pdf.headers["content-disposition"]
    # Rendered on demand and therefore repeatable: same invoice, same
    # bytes, no stored artefact that can drift from the row.
    again = await client.get(f"/api/v1/invoices/{invoice_id}/pdf", headers=headers)
    assert again.status_code == 200
    assert len(again.content) == len(pdf.content)


async def test_accounting_exports_are_finance_only_and_carry_their_columns(  # type: ignore[no-untyped-def]
    client, tenant_session_factory, crypto
) -> None:
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    buyer, _invoice_id = await _buy_one(client, tenant_session_factory, crypto, tenant_id=tenant_id)

    # The buyer just bought something; that does not make them finance.
    refused = await client.get(
        "/api/v1/invoices/export.csv", headers={"Authorization": f"Bearer {buyer}"}
    )
    assert refused.status_code == 403

    finance = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    headers = {"Authorization": f"Bearer {finance}"}

    invoices = await client.get("/api/v1/invoices/export.csv", headers=headers)
    assert invoices.status_code == 200
    assert invoices.headers["content-type"].startswith("text/csv")
    header = invoices.text.splitlines()[0]
    for column in ("number", "issued_at", "subtotal", "tax_total", "grand_total"):
        assert column in header
    assert len(invoices.text.splitlines()) > 1, "the purchase above is in this export"

    ledger = await client.get("/api/v1/ledger/export.csv", headers=headers)
    assert ledger.status_code == 200
    ledger_header = ledger.text.splitlines()[0]
    for column in ("entry_type", "amount", "vat_amount", "currency"):
        assert column in ledger_header
