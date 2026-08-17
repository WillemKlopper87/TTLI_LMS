"""Certificates and badges (02 §8, 03 §7, REQ-CRED-01…08).

Issuance is never a direct API call — REQ-CRED-01 requires it to happen
"only when the rule engine confirms every requirement is met", so the
only call site is `services/enrolment.py::complete_lesson`, at the exact
moment the last lesson's rule evaluation already passed and
`enrolment.completed_at` is set. There is deliberately no
`POST /certificates` endpoint for the same reason `POST /invoices`
doesn't exist — inventing one would be a second, unaudited path to the
same effect.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import qrcode
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, Forbidden, NotFound
from src.core.ids import uuid7
from src.core.security import new_token
from src.models.credential import (
    Badge,
    BadgeTemplate,
    Certificate,
    CertificateTemplate,
    CredentialVerification,
)
from src.models.learning import Enrolment
from src.models.user import User
from src.services import identity, push

VISIBILITY_VALUES = ("private", "public", "link_only")


class InvalidVisibility(AppError):
    pass


def _certificate_number() -> str:
    # Opaque and unguessable, deliberately not sequential (02 §8.1) —
    # unlike invoices.number, this is never meant to prove completeness
    # of a series, only to be printed and looked up.
    return f"TTLI-{secrets.token_hex(5).upper()}"


@dataclass(frozen=True, slots=True)
class IssuedCredentials:
    certificate: Certificate | None
    badge: Badge | None
    raw_verification_token: str | None


async def issue_for_completed_enrolment(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    enrolment: Enrolment,
    course_title: str,
    certificate_template_id: uuid.UUID | None,
    badge_template_id: uuid.UUID | None,
) -> IssuedCredentials:
    """Called once, from the same request that just set
    `enrolment.completed_at` — a course with neither template configured
    issues nothing, which is the normal case until an admin attaches one."""
    if certificate_template_id is None and badge_template_id is None:
        return IssuedCredentials(certificate=None, badge=None, raw_verification_token=None)

    existing = (
        await session.execute(select(Certificate).where(Certificate.enrolment_id == enrolment.id))
    ).scalar_one_or_none()
    if existing is not None:
        return IssuedCredentials(certificate=existing, badge=None, raw_verification_token=None)

    user = await session.get(User, enrolment.user_id)
    learner_name = identity.display_name(user, crypto) if user is not None else "Learner"

    certificate: Certificate | None = None
    raw_token: str | None = None
    if certificate_template_id is not None:
        template = await session.get(CertificateTemplate, certificate_template_id)
        if template is None:  # pragma: no cover - FK guarantees this
            raise NotFound("No such certificate template.")
        raw_token = new_token()
        certificate = Certificate(
            id=uuid7(),
            tenant_id=tenant_id,
            enrolment_id=enrolment.id,
            certificate_template_id=template.id,
            certificate_number=_certificate_number(),
            verification_token_encrypted=crypto.encrypt(raw_token),
            verification_token_blind_index=crypto.blind_index(raw_token),
            snapshot={
                "learner_name": learner_name,
                "course_title": course_title,
                "issuer_name": template.issuer_name,
                "signatory_name": template.signatory_name,
                "signatory_title": template.signatory_title,
                "cpd_points": template.cpd_points,
                "issued_at": datetime.now(UTC).isoformat(),
            },
        )
        session.add(certificate)
        await session.flush()

    badge: Badge | None = None
    if badge_template_id is not None:
        badge_template = await session.get(BadgeTemplate, badge_template_id)
        if badge_template is None:  # pragma: no cover - FK guarantees this
            raise NotFound("No such badge template.")
        badge = Badge(
            id=uuid7(),
            tenant_id=tenant_id,
            enrolment_id=enrolment.id,
            badge_template_id=badge_template.id,
            certificate_id=certificate.id if certificate else None,
        )
        session.add(badge)
        await session.flush()

    if certificate is not None or badge is not None:
        if certificate and badge:
            issued = "certificate and badge"
        else:
            issued = "certificate" if certificate else "badge"
        await push.notify_user(
            session,
            tenant_id=tenant_id,
            user_id=enrolment.user_id,
            title="Certificate issued!" if certificate else "Badge issued!",
            body=f"You've earned a {issued} for {course_title}.",
            url=f"/learn/{enrolment.id}",
        )

    return IssuedCredentials(certificate=certificate, badge=badge, raw_verification_token=raw_token)


def render_certificate_pdf(
    *, snapshot: dict[str, Any], certificate_number: str, verification_url: str
) -> bytes:
    """REQ-CRED-02: course, learner, issuer, dates, certificate ID, QR
    code and signatory — landscape A4, drawn directly rather than through
    a template engine, since the layout is fixed and small."""
    qr = qrcode.QRCode(border=2, box_size=4)
    qr.add_data(verification_url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    buffer = BytesIO()
    page_size = landscape(A4)
    width, height = page_size
    pdf = canvas.Canvas(buffer, pagesize=page_size)

    pdf.setStrokeColorRGB(0.56, 0.08, 0.11)
    pdf.setLineWidth(3)
    pdf.rect(10 * mm, 10 * mm, width - 20 * mm, height - 20 * mm)

    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawCentredString(width / 2, height - 40 * mm, "Certificate of Completion")

    pdf.setFont("Helvetica", 14)
    pdf.drawCentredString(width / 2, height - 60 * mm, "This certifies that")

    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawCentredString(width / 2, height - 75 * mm, str(snapshot.get("learner_name", "")))

    pdf.setFont("Helvetica", 14)
    pdf.drawCentredString(width / 2, height - 90 * mm, "has successfully completed")

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(width / 2, height - 100 * mm, str(snapshot.get("course_title", "")))

    if snapshot.get("cpd_points"):
        pdf.setFont("Helvetica", 11)
        pdf.drawCentredString(width / 2, height - 108 * mm, f"{snapshot['cpd_points']} CPD points")

    issued_at = str(snapshot.get("issued_at", ""))[:10]
    pdf.setFont("Helvetica", 10)
    pdf.drawString(25 * mm, 30 * mm, f"Issued by: {snapshot.get('issuer_name', '')}")
    pdf.drawString(25 * mm, 25 * mm, f"Certificate ID: {certificate_number}")
    pdf.drawString(25 * mm, 20 * mm, f"Issued: {issued_at}")
    signatory = f"{snapshot.get('signatory_name', '')}, {snapshot.get('signatory_title', '')}"
    pdf.drawString(25 * mm, 15 * mm, f"Signed: {signatory}")

    pdf.drawImage(
        ImageReader(qr_buffer),
        width - 55 * mm,
        15 * mm,
        30 * mm,
        30 * mm,
    )
    pdf.setFont("Helvetica", 7)
    pdf.drawCentredString(width - 40 * mm, 12 * mm, "Scan to verify")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@dataclass(frozen=True, slots=True)
class VerificationResult:
    found: bool
    holder_name: str | None = None
    course_title: str | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    status: str | None = None
    # Everything below comes from the issuance-time snapshot or the row
    # itself, never a live re-read of the template — a certificate must
    # keep saying what it said the day it was issued even if the template
    # is edited afterwards (that is what `snapshot` is for).
    credential_id: str | None = None
    issuer_name: str | None = None
    cpd_points: int | None = None
    visibility: str | None = None


async def verify(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    raw_token: str,
    ip: str | None,
    user_agent: str | None,
) -> VerificationResult:
    """03 §7's `GET /verify/{token}` — public, so this never raises for a
    miss, it returns `found=False`. Every lookup is logged (02 §8.3),
    hit or miss, since abuse detection needs the misses too. A `private`
    certificate (REQ-CRED-07) behaves exactly like a miss here — visibility
    gates the public verification page itself, not just a listing."""
    blind_index = crypto.blind_index(raw_token)
    certificate = (
        await session.execute(
            select(Certificate).where(Certificate.verification_token_blind_index == blind_index)
        )
    ).scalar_one_or_none()

    is_private = certificate is not None and certificate.visibility == "private"
    result_label = "not_found" if (certificate is None or is_private) else certificate.status
    session.add(
        CredentialVerification(
            id=uuid7(),
            tenant_id=tenant_id,
            certificate_id=certificate.id if certificate else None,
            token_blind_index=blind_index,
            ip=ip,
            user_agent=user_agent,
            result=result_label,
        )
    )
    await session.flush()

    if certificate is None or is_private:
        return VerificationResult(found=False)

    snapshot = certificate.snapshot
    cpd_points = snapshot.get("cpd_points")
    return VerificationResult(
        found=True,
        holder_name=snapshot.get("learner_name"),
        course_title=snapshot.get("course_title"),
        issued_at=certificate.issued_at,
        expires_at=certificate.expires_at,
        status=certificate.status,
        credential_id=certificate.certificate_number,
        issuer_name=snapshot.get("issuer_name"),
        cpd_points=int(cpd_points) if cpd_points is not None else None,
        visibility=certificate.visibility,
    )


def verification_url(certificate: Certificate, crypto: CryptoBox, *, public_web_url: str) -> str:
    """Reconstructs the same URL embedded in the certificate's PDF/QR code
    at issuance (`GET /badges/{id}/share/linkedin` needs it again later;
    the raw token was never persisted, only its encrypted+blind-indexed
    form — see 0014's migration docstring)."""
    raw_token = crypto.decrypt(certificate.verification_token_encrypted)
    return f"{public_web_url}/verify/{raw_token}"


async def revoke(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    certificate_id: uuid.UUID,
    reason: str,
    revoker_user_id: uuid.UUID,
) -> Certificate:
    certificate = await session.get(Certificate, certificate_id)
    if certificate is None or certificate.tenant_id != tenant_id:
        raise NotFound("No such certificate.")
    if certificate.status == "revoked":
        raise AppError("This certificate is already revoked.")
    if not reason:
        raise AppError("A reason is required to revoke a certificate.")

    certificate.status = "revoked"
    certificate.revoked_at = datetime.now(UTC)
    certificate.revoked_reason = reason
    certificate.revoked_by_user_id = revoker_user_id
    await session.flush()
    return certificate


async def get_for_enrolment(
    session: AsyncSession, *, tenant_id: uuid.UUID, enrolment_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Certificate | None, Badge | None]:
    """How a learner's own client discovers its certificate/badge IDs —
    every other endpoint in this module takes one of those IDs, and there
    is deliberately no listing/search endpoint, so this is the one lookup
    keyed by something the client already has (the enrolment it's viewing)."""
    enrolment = await session.get(Enrolment, enrolment_id)
    if enrolment is None or enrolment.tenant_id != tenant_id:
        raise NotFound("No such enrolment.")
    if enrolment.user_id != user_id:
        raise Forbidden("You do not have access to this enrolment.")

    certificate = (
        await session.execute(select(Certificate).where(Certificate.enrolment_id == enrolment_id))
    ).scalar_one_or_none()
    badge = (
        await session.execute(select(Badge).where(Badge.enrolment_id == enrolment_id))
    ).scalar_one_or_none()
    return certificate, badge


async def set_certificate_visibility(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    certificate_id: uuid.UUID,
    user_id: uuid.UUID,
    visibility: str,
) -> Certificate:
    if visibility not in VISIBILITY_VALUES:
        raise InvalidVisibility(f"visibility must be one of {VISIBILITY_VALUES}.")
    certificate = await session.get(Certificate, certificate_id)
    if certificate is None or certificate.tenant_id != tenant_id:
        raise NotFound("No such certificate.")
    enrolment = await session.get(Enrolment, certificate.enrolment_id)
    if enrolment is None or enrolment.user_id != user_id:
        raise Forbidden("You do not have access to this certificate.")

    certificate.visibility = visibility
    await session.flush()
    return certificate


async def set_badge_visibility(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    badge_id: uuid.UUID,
    user_id: uuid.UUID,
    visibility: str,
) -> Badge:
    if visibility not in VISIBILITY_VALUES:
        raise InvalidVisibility(f"visibility must be one of {VISIBILITY_VALUES}.")
    badge = await session.get(Badge, badge_id)
    if badge is None or badge.tenant_id != tenant_id:
        raise NotFound("No such badge.")
    enrolment = await session.get(Enrolment, badge.enrolment_id)
    if enrolment is None or enrolment.user_id != user_id:
        raise Forbidden("You do not have access to this badge.")

    badge.visibility = visibility
    await session.flush()
    return badge


def linkedin_share_fields(
    *, certificate: Certificate, badge: Badge | None, verification_url: str
) -> dict[str, Any]:
    """03 §7's `GET /badges/{id}/share/linkedin` — both the share URL and
    the *Add to Certification* field set (REQ-CRED-06), using LinkedIn's
    own documented `certification-name`/`organizationName` query
    parameters for the "Add to profile" deep link."""
    snapshot = certificate.snapshot
    issued = certificate.issued_at
    params = {
        "startTask": "CERTIFICATION_NAME",
        "name": snapshot.get("course_title", ""),
        "organizationName": snapshot.get("issuer_name", ""),
        "issueYear": str(issued.year),
        "issueMonth": str(issued.month),
        "certUrl": verification_url,
        "certId": certificate.certificate_number,
    }
    if certificate.expires_at:
        params["expirationYear"] = str(certificate.expires_at.year)
        params["expirationMonth"] = str(certificate.expires_at.month)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return {
        "share_url": f"https://www.linkedin.com/sharing/share-offsite/?url={verification_url}",
        "add_to_profile_url": f"https://www.linkedin.com/profile/add?{query}",
        "credential_id": certificate.certificate_number,
        "credential_url": verification_url,
    }


__all__ = [
    "InvalidVisibility",
    "IssuedCredentials",
    "VerificationResult",
    "get_for_enrolment",
    "issue_for_completed_enrolment",
    "linkedin_share_fields",
    "render_certificate_pdf",
    "revoke",
    "set_badge_visibility",
    "set_certificate_visibility",
    "verification_url",
    "verify",
]
