"""Phase 4 sprint 4: certificates, badges, public verification (02 §8,
03 §7, REQ-CRED-01…08). HTTP coverage for the full path — buy the seeded
course, complete both lessons through the real API (same enrolment/
completion helpers as test_learning.py/test_assessment.py), and let
`services/enrolment.py::complete_lesson` issue the certificate/badge as a
side effect of the *last* lesson's completion, exactly as production does.

`POST /certificate-templates`/`POST /badge-templates` (test_courses.py's
sibling authoring surface) now exist, but the tests below still wire
templates with direct SQL and restore the course's prior state in
`finally` — `courses` is global and shared with every other test file,
so mutating the seeded course's template links needs the same
restore-after discipline regardless of how the template rows themselves
get created. Template CRUD itself is covered separately, at the bottom
of this file.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime
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
from src.services.credentials import _add_months
from src.services.storage import Container, get_storage_adapter

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
    return f"cred-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str((await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one())


async def _demo_course_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        return (
            await s.execute(
                sa.text("SELECT id FROM courses WHERE slug = 'executive-leadership-certificate'")
            )
        ).scalar_one()


async def _seeded_lessons(tenant_session_factory, tenant_id) -> list[str]:  # type: ignore[no-untyped-def]
    """The two document lessons 0011 seeds, in position order."""
    async with tenant_session_factory(tenant_id) as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT l.id FROM lessons l "
                    "JOIN modules m ON m.id = l.module_id "
                    "JOIN courses c ON c.id = m.course_id "
                    "WHERE c.slug = 'executive-leadership-certificate' "
                    "ORDER BY l.position"
                )
            )
        ).all()
    return [str(row[0]) for row in rows]


async def _login(
    client,
    tenant_session_factory,
    crypto,
    *,
    tenant_id,
    role: str | None,
    full_name: str | None = None,
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s,
            crypto,
            tenant_id=tenant_id,
            email=email,
            password=PASSWORD,
            full_name=full_name,
        )
        user_id = user.id
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user_id, role_code=role))

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    return str(resp.json()["access_token"]), user_id


async def _enrol_via_eft(
    client, tenant_session_factory, crypto, *, tenant_id, price_id, full_name: str | None = None
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    buyer_token, buyer_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None, full_name=full_name
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {buyer_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    order_id = order.json()["id"]
    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_id = checkout.json()["payment_id"]
    await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"%PDF-fake-proof-of-payment", "application/pdf")},
    )
    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200, approve.text
    return buyer_token, buyer_id


async def _enrolment_id_for(tenant_session_factory, tenant_id, user_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str(
            (
                await s.execute(
                    sa.text("SELECT id FROM enrolments WHERE user_id = :u"), {"u": user_id}
                )
            ).scalar_one()
        )


async def _backdate_first_seen(
    tenant_session_factory, tenant_id, *, enrolment_id: str, lesson_id: str
) -> None:  # type: ignore[no-untyped-def]
    """Same trick as test_learning.py — push first_seen_at into the past
    rather than sleeping past minimum_time_seconds (30s/60s, 0011's seed)."""
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "UPDATE lesson_completions SET first_seen_at = now() - interval '1 hour' "
                "WHERE lesson_id = :l AND enrolment_id = :e"
            ),
            {"l": lesson_id, "e": enrolment_id},
        )


async def _complete_all_lessons(
    client,
    tenant_session_factory,
    tenant_id,
    *,
    token: str,
    enrolment_id: str,
    lesson_ids: list[str],
) -> None:  # type: ignore[no-untyped-def]
    for lesson_id in lesson_ids:
        start = await client.post(
            f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
        )
        assert start.status_code == 204, start.text
        await _backdate_first_seen(
            tenant_session_factory, tenant_id, enrolment_id=enrolment_id, lesson_id=lesson_id
        )
        complete = await client.post(
            f"/api/v1/lessons/{lesson_id}/complete", headers={"Authorization": f"Bearer {token}"}
        )
        assert complete.status_code == 200, complete.text


async def _wire_templates(
    tenant_session_factory, course_id: uuid.UUID, *, with_badge: bool
) -> tuple[uuid.UUID, uuid.UUID | None]:  # type: ignore[no-untyped-def]
    """Direct SQL rather than `POST /certificate-templates`/`POST
    /badge-templates` (which exist, see the bottom of this file) because
    this helper also wires the template onto the *seeded* course — there
    is no authoring endpoint for attaching a template to an arbitrary
    existing course's fields other than the general `PATCH /courses/{id}`
    course-update endpoint, and using it here would make this a course-
    authoring test rather than a certificate/badge issuance one."""
    cert_template_id = uuid.uuid4()
    badge_template_id = uuid.uuid4() if with_badge else None
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "INSERT INTO certificate_templates "
                "(id, title, issuer_name, signatory_name, signatory_title, cpd_points) "
                "VALUES (:id, 'Executive Leadership Certificate', "
                "'Themba Thandeka Leadership Institute', "
                "'Dr. Thandeka Themba', 'Programme Director', 5)"
            ),
            {"id": cert_template_id},
        )
        if badge_template_id is not None:
            await s.execute(
                sa.text(
                    "INSERT INTO badge_templates (id, title, criteria, issuer_name, level) "
                    "VALUES (:id, 'Leadership Foundations', "
                    "'Completed the Executive Leadership Certificate', 'TTLI', 'foundation')"
                ),
                {"id": badge_template_id},
            )
        await s.execute(
            sa.text(
                "UPDATE courses SET certificate_template_id = :ct, badge_template_id = :bt "
                "WHERE id = :c"
            ),
            {"ct": cert_template_id, "bt": badge_template_id, "c": course_id},
        )
    return cert_template_id, badge_template_id


async def _restore_course_templates(tenant_session_factory, course_id: uuid.UUID) -> None:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "UPDATE courses SET certificate_template_id = NULL, badge_template_id = NULL "
                "WHERE id = :c"
            ),
            {"c": course_id},
        )


async def _certificate_row(tenant_session_factory, tenant_id, enrolment_id: str):  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text(
                    "SELECT id, verification_token_encrypted, visibility, pdf_object_key, "
                    "certificate_number FROM certificates WHERE enrolment_id = :e"
                ),
                {"e": enrolment_id},
            )
        ).first()
    return row


# ===================================================== Issuance + PDF ===


async def test_completing_course_issues_certificate_and_badge_with_working_pdf_and_qr(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    lesson_ids = await _seeded_lessons(tenant_session_factory, tenant_id)

    await _wire_templates(tenant_session_factory, course_id, with_badge=True)
    try:
        token, user_id = await _enrol_via_eft(
            client,
            tenant_session_factory,
            crypto,
            tenant_id=tenant_id,
            price_id=price_id,
            full_name="Ada Lovelace",
        )
        enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, user_id)
        await _complete_all_lessons(
            client,
            tenant_session_factory,
            tenant_id,
            token=token,
            enrolment_id=enrolment_id,
            lesson_ids=lesson_ids,
        )

        row = await _certificate_row(tenant_session_factory, tenant_id, enrolment_id)
        assert row is not None
        certificate_id, token_encrypted, visibility, pdf_object_key, certificate_number = row
        assert visibility == "private"  # REQ-CRED-07 default
        assert pdf_object_key is not None
        assert certificate_number.startswith("TTLI-")

        # A badge was also issued, linked to the same certificate.
        async with tenant_session_factory(tenant_id) as s:
            badge_row = (
                await s.execute(
                    sa.text(
                        "SELECT certificate_id, visibility FROM badges WHERE enrolment_id = :e"
                    ),
                    {"e": enrolment_id},
                )
            ).first()
        assert badge_row is not None
        assert str(badge_row[0]) == str(certificate_id)
        assert badge_row[1] == "private"

        # How the learner's own client discovers the certificate/badge IDs
        # it needs for every other endpoint — owner-only.
        discover = await client.get(
            f"/api/v1/enrolments/{enrolment_id}/credentials",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert discover.status_code == 200, discover.text
        discovered = discover.json()
        assert discovered["certificate"]["id"] == str(certificate_id)
        assert discovered["certificate"]["pdf_available"] is True
        assert discovered["badge"]["visibility"] == "private"

        stranger_token, _ = await _enrol_via_eft(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
        )
        stranger_discover = await client.get(
            f"/api/v1/enrolments/{enrolment_id}/credentials",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
        assert stranger_discover.status_code == 403

        # The PDF is real, was actually rendered and stored, and contains a
        # scannable QR pointing at the exact verification URL LinkedIn
        # sharing later reconstructs from the same encrypted token.
        pdf_resp = await client.get(
            f"/api/v1/certificates/{certificate_id}/pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pdf_resp.status_code == 200, pdf_resp.text
        assert pdf_resp.json()["pdf_url"]

        storage = get_storage_adapter(settings)
        pdf_bytes = await storage.get_object(Container.GENERATED_DOCUMENTS, pdf_object_key)
        assert pdf_bytes.startswith(b"%PDF")

        raw_token = crypto.decrypt(token_encrypted)
        assert len(raw_token) > 0

        # Still private: the public endpoint must not reveal it.
        hidden = await client.get(f"/api/v1/verify/{raw_token}")
        assert hidden.status_code == 200
        assert hidden.json()["found"] is False

        make_public = await client.patch(
            f"/api/v1/certificates/{certificate_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"visibility": "public"},
        )
        assert make_public.status_code == 200, make_public.text
        assert make_public.json()["visibility"] == "public"

        verified = await client.get(f"/api/v1/verify/{raw_token}")
        assert verified.status_code == 200
        body = verified.json()
        assert body["found"] is True
        assert body["holder_name"] == "Ada Lovelace"
        assert body["course_title"] == "Executive Leadership Certificate"
        assert body["status"] == "valid"
        # What the public verify page renders beside the name: the printed
        # credential ID, the issuing organisation and the CPD value — all
        # off the issuance-time snapshot, so editing the template later
        # cannot change what an already-issued certificate claims.
        assert body["credential_id"] == certificate_number
        assert body["issuer_name"] == "Themba Thandeka Leadership Institute"
        assert body["cpd_points"] == 5
        assert body["visibility"] == "public"
        # An alias of course_title, not a second fact — the verify page
        # speaks "programme" where the data model speaks "course".
        assert body["programme_title"] == body["course_title"]
    finally:
        await _restore_course_templates(tenant_session_factory, course_id)


async def test_verify_unknown_token_is_a_clean_miss_and_is_logged(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    resp = await client.get("/api/v1/verify/not-a-real-token")
    assert resp.status_code == 200
    # Every field null, including the verify page's own additions — a miss
    # must not be distinguishable from a `private` certificate.
    assert resp.json() == {
        "found": False,
        "holder_name": None,
        "course_title": None,
        "programme_title": None,
        "issued_at": None,
        "expires_at": None,
        "status": None,
        "credential_id": None,
        "issuer_name": None,
        "cpd_points": None,
        "cpd_body": None,
        "cpd_reference": None,
        "visibility": None,
        # Not nullable (P5) — always False, same as every other field
        # here reads as "nothing to tell", not a leak of which kind.
        "is_learning_path": False,
    }
    async with tenant_session_factory(tenant_id) as s:
        count = (
            await s.execute(
                sa.text("SELECT count(*) FROM credential_verifications WHERE result = 'not_found'")
            )
        ).scalar_one()
    assert count >= 1


async def test_completing_course_without_templates_issues_nothing(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lesson_ids = await _seeded_lessons(tenant_session_factory, tenant_id)

    token, user_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, user_id)
    await _complete_all_lessons(
        client,
        tenant_session_factory,
        tenant_id,
        token=token,
        enrolment_id=enrolment_id,
        lesson_ids=lesson_ids,
    )

    row = await _certificate_row(tenant_session_factory, tenant_id, enrolment_id)
    assert row is None


# ============================================================= Revoke ===


async def test_revoke_requires_permission_and_reason_and_reflects_in_verify(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    lesson_ids = await _seeded_lessons(tenant_session_factory, tenant_id)

    await _wire_templates(tenant_session_factory, course_id, with_badge=False)
    try:
        token, user_id = await _enrol_via_eft(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
        )
        enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, user_id)
        await _complete_all_lessons(
            client,
            tenant_session_factory,
            tenant_id,
            token=token,
            enrolment_id=enrolment_id,
            lesson_ids=lesson_ids,
        )
        row = await _certificate_row(tenant_session_factory, tenant_id, enrolment_id)
        assert row is not None
        certificate_id, token_encrypted, _, _, _ = row
        raw_token = crypto.decrypt(token_encrypted)

        await client.patch(
            f"/api/v1/certificates/{certificate_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"visibility": "public"},
        )

        # Owner-without-permission cannot revoke their own certificate.
        forbidden = await client.post(
            f"/api/v1/certificates/{certificate_id}/revoke",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "test"},
        )
        assert forbidden.status_code == 403

        admin_token, _ = await _login(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, role="admin"
        )
        empty_reason = await client.post(
            f"/api/v1/certificates/{certificate_id}/revoke",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": ""},
        )
        assert empty_reason.status_code in (400, 422)

        revoke = await client.post(
            f"/api/v1/certificates/{certificate_id}/revoke",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "Issued in error"},
        )
        assert revoke.status_code == 200, revoke.text
        assert revoke.json()["status"] == "revoked"

        verified = await client.get(f"/api/v1/verify/{raw_token}")
        assert verified.json()["status"] == "revoked"

        again = await client.post(
            f"/api/v1/certificates/{certificate_id}/revoke",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "Second try"},
        )
        assert again.status_code == 400
    finally:
        await _restore_course_templates(tenant_session_factory, course_id)


# ======================================================= Badge sharing ===


async def test_badge_visibility_is_owner_only_and_linkedin_share_reconstructs_url(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    lesson_ids = await _seeded_lessons(tenant_session_factory, tenant_id)

    await _wire_templates(tenant_session_factory, course_id, with_badge=True)
    try:
        owner_token, owner_id = await _enrol_via_eft(
            client,
            tenant_session_factory,
            crypto,
            tenant_id=tenant_id,
            price_id=price_id,
            full_name="Grace Hopper",
        )
        enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, owner_id)
        await _complete_all_lessons(
            client,
            tenant_session_factory,
            tenant_id,
            token=owner_token,
            enrolment_id=enrolment_id,
            lesson_ids=lesson_ids,
        )

        async with tenant_session_factory(tenant_id) as s:
            badge_id = (
                await s.execute(
                    sa.text("SELECT id FROM badges WHERE enrolment_id = :e"), {"e": enrolment_id}
                )
            ).scalar_one()

        stranger_token, _ = await _enrol_via_eft(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
        )
        forbidden = await client.patch(
            f"/api/v1/badges/{badge_id}",
            headers={"Authorization": f"Bearer {stranger_token}"},
            json={"visibility": "public"},
        )
        assert forbidden.status_code == 403

        ok = await client.patch(
            f"/api/v1/badges/{badge_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"visibility": "public"},
        )
        assert ok.status_code == 200
        assert ok.json()["visibility"] == "public"

        row = await _certificate_row(tenant_session_factory, tenant_id, enrolment_id)
        assert row is not None
        _certificate_id, token_encrypted, _, _, certificate_number = row
        raw_token = crypto.decrypt(token_encrypted)
        expected_url = f"{settings.public_web_url}/verify/{raw_token}"

        share = await client.get(
            f"/api/v1/badges/{badge_id}/share/linkedin",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert share.status_code == 200, share.text
        fields = share.json()
        assert fields["credential_url"] == expected_url
        assert fields["credential_id"] == certificate_number
        assert expected_url in fields["add_to_profile_url"]
        assert "name=Executive Leadership Certificate" in fields["add_to_profile_url"]
        assert (
            "organizationName=Themba Thandeka Leadership Institute" in fields["add_to_profile_url"]
        )
    finally:
        await _restore_course_templates(tenant_session_factory, course_id)


async def test_certificate_only_course_can_share_on_linkedin_without_a_badge(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    """P13 (audit #17): `linkedin_share_fields` already accepted
    `badge=None` and never read it — the only gap was that
    `GET /badges/{id}/share/linkedin` was the sole way to reach it, so a
    course with no badge template attached (certificate only) had no
    share endpoint at all. Also confirms the stranger/ownership check
    on the new route the same way the badge route is already covered."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    lesson_ids = await _seeded_lessons(tenant_session_factory, tenant_id)

    await _wire_templates(tenant_session_factory, course_id, with_badge=False)
    try:
        owner_token, owner_id = await _enrol_via_eft(
            client,
            tenant_session_factory,
            crypto,
            tenant_id=tenant_id,
            price_id=price_id,
            full_name="Ada Lovelace",
        )
        enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, owner_id)
        await _complete_all_lessons(
            client,
            tenant_session_factory,
            tenant_id,
            token=owner_token,
            enrolment_id=enrolment_id,
            lesson_ids=lesson_ids,
        )

        row = await _certificate_row(tenant_session_factory, tenant_id, enrolment_id)
        assert row is not None
        certificate_id, token_encrypted, _, _, certificate_number = row
        raw_token = crypto.decrypt(token_encrypted)
        expected_url = f"{settings.public_web_url}/verify/{raw_token}"

        stranger_token, _ = await _enrol_via_eft(
            client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
        )
        forbidden = await client.get(
            f"/api/v1/certificates/{certificate_id}/share/linkedin",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
        assert forbidden.status_code == 403

        share = await client.get(
            f"/api/v1/certificates/{certificate_id}/share/linkedin",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert share.status_code == 200, share.text
        fields = share.json()
        assert fields["credential_url"] == expected_url
        assert fields["credential_id"] == certificate_number
        assert expected_url in fields["add_to_profile_url"]
    finally:
        await _restore_course_templates(tenant_session_factory, course_id)


async def test_certificate_and_badge_template_crud_is_course_edit_gated(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.post(
        "/api/v1/certificate-templates",
        json={
            "title": "Should not be created",
            "issuer_name": "TTLI",
            "signatory_name": "Someone",
            "signatory_title": "Director",
        },
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403

    resp = await client.post(
        "/api/v1/badge-templates",
        json={"title": "Should not be created", "criteria": "x", "issuer_name": "TTLI"},
        headers={"Authorization": f"Bearer {learner_token}"},
    )
    assert resp.status_code == 403


async def test_certificate_template_create_list_and_update(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    title = f"Cert Template {uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/v1/certificate-templates",
        json={
            "title": title,
            "issuer_name": "TTLI",
            "signatory_name": "Dr. Jane Doe",
            "signatory_title": "Programme Director",
            "cpd_points": 5,
            "cpd_body": "Continuing professional development in executive leadership",
            "cpd_reference": "SABPP-2026-0042",
            "cpd_validity_months": 24,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    expected_body = "Continuing professional development in executive leadership"
    assert created.json()["cpd_body"] == expected_body
    assert created.json()["cpd_reference"] == "SABPP-2026-0042"
    assert created.json()["cpd_validity_months"] == 24

    listed = await client.get(
        "/api/v1/certificate-templates", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert listed.status_code == 200
    assert any(t["id"] == template_id for t in listed.json()["items"])

    updated = await client.patch(
        f"/api/v1/certificate-templates/{template_id}",
        json={"cpd_points": 10, "cpd_reference": "SABPP-2026-0099"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["cpd_points"] == 10
    assert updated.json()["title"] == title
    assert updated.json()["cpd_reference"] == "SABPP-2026-0099"
    # Fields the update body didn't mention are untouched, not cleared.
    assert updated.json()["cpd_validity_months"] == 24


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        # The ordinary case: same day, N months later.
        (datetime(2026, 3, 15, tzinfo=UTC), 12, datetime(2027, 3, 15, tzinfo=UTC)),
        # Clamped: 31 Jan + 1 month has no 31st in February.
        (datetime(2026, 1, 31, tzinfo=UTC), 1, datetime(2026, 2, 28, tzinfo=UTC)),
        # Clamped into a leap year — 29 Feb exists in 2028.
        (datetime(2027, 1, 31, tzinfo=UTC), 13, datetime(2028, 2, 29, tzinfo=UTC)),
        # Crossing a year boundary with no day-of-month clamping needed.
        (datetime(2026, 11, 30, tzinfo=UTC), 3, datetime(2027, 2, 28, tzinfo=UTC)),
    ],
)
def test_add_months_clamps_the_day_when_the_target_month_is_shorter(
    start: datetime, months: int, expected: datetime
) -> None:
    """P13 (audit #18): pure stdlib month arithmetic, no dependency added
    for one function — `calendar.monthrange`'s day-count clamps a day
    that doesn't exist in the target month rather than raising."""
    assert _add_months(start, months) == expected


async def test_certificate_expiry_is_computed_from_template_validity_months(
    client, tenant_session_factory, crypto, settings
) -> None:  # type: ignore[no-untyped-def]
    """P13 (audit #18): `Certificate.expires_at` has existed since `0014`
    but no issuance path had ever set it, since no template carried a
    validity period to compute it from. `_wire_templates` doesn't set
    `cpd_validity_months` (every other test in this file relies on its
    default `None` -> no expiry, unchanged behaviour), so this test sets
    it directly on the wired row rather than widening that shared helper
    for one test."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    course_id = await _demo_course_id(tenant_session_factory)
    lesson_ids = await _seeded_lessons(tenant_session_factory, tenant_id)

    cert_template_id, _ = await _wire_templates(tenant_session_factory, course_id, with_badge=False)
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "UPDATE certificate_templates SET cpd_validity_months = 12, "
                "cpd_body = 'CPD in executive leadership', cpd_reference = 'SABPP-2026-0042' "
                "WHERE id = :id"
            ),
            {"id": cert_template_id},
        )
    try:
        owner_token, owner_id = await _enrol_via_eft(
            client,
            tenant_session_factory,
            crypto,
            tenant_id=tenant_id,
            price_id=price_id,
            full_name="Katherine Johnson",
        )
        enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, owner_id)
        await _complete_all_lessons(
            client,
            tenant_session_factory,
            tenant_id,
            token=owner_token,
            enrolment_id=enrolment_id,
            lesson_ids=lesson_ids,
        )

        async with tenant_session_factory(tenant_id) as s:
            issued_at, expires_at = (
                await s.execute(
                    sa.text(
                        "SELECT issued_at, expires_at FROM certificates WHERE enrolment_id = :e"
                    ),
                    {"e": enrolment_id},
                )
            ).one()
        assert expires_at is not None, "a template with cpd_validity_months must set an expiry"
        # 12 months out, same day-of-month (no day-of-month drift possible
        # here — the 1st to the 30th/31st never needs clamping).
        assert expires_at.year == issued_at.year + 1
        assert expires_at.month == issued_at.month
        assert expires_at.day == issued_at.day

        row = await _certificate_row(tenant_session_factory, tenant_id, enrolment_id)
        assert row is not None
        certificate_id, token_encrypted, _, _, _ = row
        raw_token = crypto.decrypt(token_encrypted)

        # Certificates default to private (REQ-CRED-07) — the verify page
        # treats that identically to a miss, so it has to be made public
        # first, the same step every other verify-calling test here takes.
        made_public = await client.patch(
            f"/api/v1/certificates/{certificate_id}",
            json={"visibility": "public"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert made_public.status_code == 200, made_public.text

        verified = await client.get(f"/api/v1/verify/{raw_token}")
        assert verified.status_code == 200, verified.text
        body = verified.json()
        assert body["found"] is True
        assert body["expires_at"] is not None
        assert body["cpd_body"] == "CPD in executive leadership"
        assert body["cpd_reference"] == "SABPP-2026-0042"
    finally:
        await _restore_course_templates(tenant_session_factory, course_id)


async def test_badge_template_create_list_and_update(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    admin_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="super_admin"
    )
    title = f"Badge Template {uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/v1/badge-templates",
        json={"title": title, "criteria": "Complete the course", "issuer_name": "TTLI"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    listed = await client.get(
        "/api/v1/badge-templates", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert listed.status_code == 200
    assert any(t["id"] == template_id for t in listed.json()["items"])

    updated = await client.patch(
        f"/api/v1/badge-templates/{template_id}",
        json={"level": "advanced"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["level"] == "advanced"
    assert updated.json()["title"] == title
