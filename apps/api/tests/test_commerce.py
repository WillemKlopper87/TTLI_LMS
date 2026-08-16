"""Commerce foundation + the EFT purchase path (02 §6, 03 §5.1/5.3/5.4/5.6,
REQ-PAY-03/05/08/09): HTTP coverage for the full order lifecycle, plus
raw-SQL checks on ledger append-only enforcement and sequential invoice
numbering — the same reason test_rls.py and test_leads.py go around the ORM
for those two things.
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
        pytest.skip(
            "no Redis on the configured REDIS_URL — run: "
            "docker compose -f infra/docker-compose.yml up -d redis"
        )
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
    return f"buyer-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        price_id = (await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one()
    return str(price_id)


async def _login(
    client, tenant_session_factory, crypto, *, tenant_id, role: str | None
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        user_id = user.id
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user_id, role_code=role))

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    return str(resp.json()["access_token"]), user_id


async def _create_order(client, token: str, price_id: str, **overrides: object) -> dict:
    body: dict[str, object] = {
        "currency": "ZAR",
        "customer_type": "individual",
        "lines": [{"price_id": price_id, "quantity": 1}],
    }
    body.update(overrides)
    resp = await client.post(
        "/api/v1/orders",
        json=body,
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_order_resolves_price_and_tax_serverside(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    token, _ = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    order = await _create_order(client, token, price_id)
    assert order["status"] == "pending_payment"
    # Seeded price is 4500.00, ZAR VAT is 15% (0009's seed) — 675.00 tax,
    # 5175.00 total. Asserted here, not assumed, since a client never
    # supplies these amounts (03 §5.1).
    assert order["subtotal"] == "4500.00"
    assert order["tax_total"] == "675.00"
    assert order["grand_total"] == "5175.00"


async def test_international_customer_is_refused_not_guessed(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    token, user_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    resp = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "international",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "TAX_UNRESOLVED"

    # Regression: create_order() used to flush the Order row before
    # resolving tax, so a refusal here left an orphaned empty 'draft' order
    # behind — get_session() commits whatever an AppError leaves flushed.
    async with tenant_session_factory(tenant_id) as s:
        orphaned = (
            await s.execute(
                sa.text("SELECT count(*) FROM orders WHERE user_id = :u"), {"u": user_id}
            )
        ).scalar_one()
    assert orphaned == 0


async def test_create_order_rejects_unknown_price(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token, _ = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    resp = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": str(uuid.uuid4()), "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "ORDER_ERROR"


async def test_full_eft_happy_path_issues_invoice_grants_entitlement_and_ledger(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer_token, buyer_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _finance_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )

    order = await _create_order(client, buyer_token, price_id)
    order_id = order["id"]

    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    assert checkout.status_code == 200
    payment_id = checkout.json()["payment_id"]
    assert checkout.json()["payment_reference"]

    proof = await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"%PDF-fake-proof-of-payment", "application/pdf")},
    )
    assert proof.status_code == 204

    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200, approve.text
    invoice = approve.json()
    assert invoice["number"].startswith("INV-")
    assert invoice["status"] == "issued"
    assert invoice["grand_total"] == "5175.00"

    async with tenant_session_factory(tenant_id) as s:
        order_row = (
            await s.execute(sa.text("SELECT status FROM orders WHERE id = :i"), {"i": order_id})
        ).scalar_one()
        assert order_row == "fulfilled"

        entitlement = (
            await s.execute(
                sa.text(
                    "SELECT kind, quantity, source_order_id FROM entitlements WHERE user_id = :u"
                ),
                {"u": buyer_id},
            )
        ).first()
        assert entitlement is not None
        assert entitlement[0] == "course"
        assert entitlement[1] == 1
        assert str(entitlement[2]) == order_id

        ledger_rows = (
            await s.execute(
                sa.text(
                    "SELECT entry_type, amount, reference FROM ledger_entries "
                    "WHERE reference = :ref OR entity_id = :inv "
                    "ORDER BY created_at"
                ),
                {"ref": checkout.json()["payment_reference"], "inv": invoice["id"]},
            )
        ).all()
        entry_types = {row[0] for row in ledger_rows}
        assert "payment_received" in entry_types
        assert "invoice_issued" in entry_types


async def test_eft_reject_then_resubmit_then_approve(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _finance_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )

    order = await _create_order(client, buyer_token, price_id)
    order_id = order["id"]
    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_id = checkout.json()["payment_id"]

    await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"bad proof", "application/pdf")},
    )

    reject = await client.post(
        f"/api/v1/payments/{payment_id}/reject",
        json={"reason": "Reference does not match."},
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert reject.status_code == 204

    order_after_reject = await client.get(
        f"/api/v1/orders/{order_id}", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert order_after_reject.json()["status"] == "eft_rejected"

    # 01 §4.1: "eft_rejected returns to eft_pending_proof on resubmission."
    resubmit = await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof2.pdf", b"corrected proof", "application/pdf")},
    )
    assert resubmit.status_code == 204

    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200


async def test_payment_approve_requires_permission(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    order = await _create_order(client, buyer_token, price_id)
    checkout = await client.post(
        f"/api/v1/orders/{order['id']}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_id = checkout.json()["payment_id"]

    resp = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {buyer_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 403


async def test_order_ownership_is_enforced(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    owner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    other_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    order = await _create_order(client, owner_token, price_id)

    resp = await client.get(
        f"/api/v1/orders/{order['id']}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert resp.status_code == 403


async def test_invoice_numbers_are_sequential_and_gapless(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )

    sequences: list[int] = []
    for _ in range(2):
        buyer_token, _ = await _login(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
        )
        order = await _create_order(client, buyer_token, price_id)
        checkout = await client.post(
            f"/api/v1/orders/{order['id']}/checkout/eft",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )
        payment_id = checkout.json()["payment_id"]
        await client.post(
            f"/api/v1/orders/{order['id']}/payment-proof",
            headers={"Authorization": f"Bearer {buyer_token}"},
            files={"file": ("proof.pdf", b"proof", "application/pdf")},
        )
        approve = await client.post(
            f"/api/v1/payments/{payment_id}/approve",
            headers={
                "Authorization": f"Bearer {finance_token}",
                "Idempotency-Key": uuid.uuid4().hex,
            },
        )
        number = approve.json()["number"]
        sequences.append(int(number.rsplit("-", 1)[1]))

    # Not asserting an absolute starting value — this DB is shared across
    # test runs — only that two invoices issued back to back in the same
    # series get consecutive, gapless numbers (REQ-PAY-09).
    assert sequences[1] == sequences[0] + 1


async def test_ledger_entries_are_append_only(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )

    order = await _create_order(client, buyer_token, price_id)
    checkout = await client.post(
        f"/api/v1/orders/{order['id']}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_id = checkout.json()["payment_id"]
    await client.post(
        f"/api/v1/orders/{order['id']}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"proof", "application/pdf")},
    )
    await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )

    async with tenant_session_factory(tenant_id) as s:
        entry_id = (
            await s.execute(
                sa.text("SELECT id FROM ledger_entries WHERE reference = :ref"),
                {"ref": checkout.json()["payment_reference"]},
            )
        ).scalar_one()
        with pytest.raises(sa.exc.DBAPIError, match="permission denied"):
            await s.execute(
                sa.text("UPDATE ledger_entries SET amount = 999 WHERE id = :i"), {"i": entry_id}
            )


async def test_list_products_returns_the_seeded_catalogue(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.get("/api/v1/products")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) >= 1
    product = body["items"][0]
    assert product["prices"], "seeded product should carry at least one price"
    assert product["prices"][0]["currency"] == "ZAR"


async def test_pending_payments_requires_permission(client, tenant_session_factory, crypto) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    token, _ = await _login(client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None)

    resp = await client.get("/api/v1/payments", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_pending_payments_lists_only_awaiting_approval(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )

    order = await _create_order(client, buyer_token, price_id)
    checkout = await client.post(
        f"/api/v1/orders/{order['id']}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_reference = checkout.json()["payment_reference"]

    # Not yet in the queue — no proof uploaded, order is still eft_pending_proof.
    before = await client.get(
        "/api/v1/payments", headers={"Authorization": f"Bearer {finance_token}"}
    )
    assert before.status_code == 200
    assert payment_reference not in {row["payment_reference"] for row in before.json()["items"]}

    await client.post(
        f"/api/v1/orders/{order['id']}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"proof", "application/pdf")},
    )

    after = await client.get(
        "/api/v1/payments", headers={"Authorization": f"Bearer {finance_token}"}
    )
    assert after.status_code == 200
    match = next(
        row for row in after.json()["items"] if row["payment_reference"] == payment_reference
    )
    assert match["proof_uploaded"] is True
    assert match["amount"] == "5175.00"


async def test_pending_payments_survives_an_undecryptable_buyer_email(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """A row encrypted under a since-rotated key (a real incident found
    live in this environment: 94/95 dev-DB orders had exactly this after
    an earlier key rotation) must not crash the whole finance queue —
    every other payment still has to be visible and actionable."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer_token, buyer_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )

    order = await _create_order(client, buyer_token, price_id)
    checkout = await client.post(
        f"/api/v1/orders/{order['id']}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_reference = checkout.json()["payment_reference"]
    await client.post(
        f"/api/v1/orders/{order['id']}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"proof", "application/pdf")},
    )

    # Corrupt the ciphertext in place — the same failure shape a rotated
    # encryption key produces (AES-GCM's auth tag no longer verifies).
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text("UPDATE users SET email_encrypted = :garbage WHERE id = :u"),
            {"garbage": b"\x00" * 44, "u": buyer_id},
        )

    resp = await client.get(
        "/api/v1/payments", headers={"Authorization": f"Bearer {finance_token}"}
    )
    assert resp.status_code == 200, resp.text
    match = next(
        row for row in resp.json()["items"] if row["payment_reference"] == payment_reference
    )
    assert "unreadable" in match["buyer_email"]


# The EICAR standard antivirus test file (https://www.eicar.org/) — every
# real antivirus engine, including ClamAV, is configured to flag it by
# convention. Not an actual virus.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


async def test_infected_payment_proof_is_refused_and_order_does_not_advance(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    # `client` already skips if Redis is unreachable; ClamAV needs its own
    # check since it's a separate optional local service.
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((settings.clamav_host, settings.clamav_port))
    except OSError:
        pytest.skip(
            "no ClamAV on the configured CLAMAV_HOST/PORT — run: "
            "docker compose -f infra/docker-compose.yml up -d clamav"
        )
    finally:
        sock.close()

    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    buyer_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )

    order = await _create_order(client, buyer_token, price_id)
    await client.post(
        f"/api/v1/orders/{order['id']}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )

    resp = await client.post(
        f"/api/v1/orders/{order['id']}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", EICAR, "application/pdf")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"]["signature"]

    # Refused before it ever reached storage or the order's own state
    # machine — still eft_pending_proof, not eft_pending_approval.
    order_after = await client.get(
        f"/api/v1/orders/{order['id']}", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert order_after.json()["status"] == "eft_pending_proof"
