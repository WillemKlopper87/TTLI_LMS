"""Certificates and badges (02 §8, 03 §7, REQ-CRED-01…08).

`GET /verify/{token}` is the one genuinely public, unauthenticated route
in this file — rate-limited the same way `POST /leads` is (03 §1.8 has no
dedicated number for this either), and every lookup is logged whether it
hits or misses (services/credentials.py::verify), which is what makes the
log double as abuse detection rather than just a hit counter.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from src.core.config import get_settings
from src.core.deps import (
    CryptoDep,
    PrincipalDep,
    RedisDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    TenantDep,
)
from src.core.errors import Forbidden, NotFound, TooManyAttempts
from src.core.ids import uuid7
from src.core.net import client_ip
from src.models.audit import AuditAction
from src.models.credential import Badge, BadgeTemplate, Certificate, CertificateTemplate
from src.models.learning import Enrolment
from src.schemas.credentials import (
    BadgeResponse,
    BadgeTemplateCreateRequest,
    BadgeTemplateResponse,
    BadgeTemplatesPageResponse,
    BadgeTemplateUpdateRequest,
    CertificatePdfResponse,
    CertificateResponse,
    CertificateTemplateCreateRequest,
    CertificateTemplateResponse,
    CertificateTemplatesPageResponse,
    CertificateTemplateUpdateRequest,
    EnrolmentCredentialsResponse,
    LinkedInShareResponse,
    RevokeCertificateRequest,
    VerificationResponse,
    VisibilityRequest,
)
from src.services import audit, rate_limit
from src.services import credentials as credentials_service
from src.services.storage import Container

router = APIRouter(tags=["credentials"])

VERIFY_RATE_LIMIT_PER_IP = 20
VERIFY_RATE_LIMIT_WINDOW_SECONDS = 3600


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


def _client_ip(request: Request) -> str | None:
    return client_ip(request, trust_x_forwarded_for=get_settings().trust_x_forwarded_for)


async def _owns_certificate(
    session: SessionDep, certificate: Certificate, user_id: uuid.UUID
) -> bool:
    enrolment = await session.get(Enrolment, certificate.enrolment_id)
    return enrolment is not None and enrolment.user_id == user_id


@router.get("/enrolments/{enrolment_id}/credentials", response_model=EnrolmentCredentialsResponse)
async def get_enrolment_credentials(
    enrolment_id: str, principal: PrincipalDep, session: SessionDep
) -> EnrolmentCredentialsResponse:
    certificate, badge = await credentials_service.get_for_enrolment(
        session,
        tenant_id=principal.tenant_id,
        enrolment_id=_parse_uuid(enrolment_id),
        user_id=principal.user_id,
    )
    return EnrolmentCredentialsResponse(
        certificate=CertificateResponse(
            id=str(certificate.id),
            certificate_number=certificate.certificate_number,
            status=certificate.status,
            visibility=certificate.visibility,
            issued_at=certificate.issued_at,
            revoked_reason=certificate.revoked_reason,
            pdf_available=certificate.pdf_object_key is not None,
        )
        if certificate is not None
        else None,
        badge=BadgeResponse(
            id=str(badge.id), visibility=badge.visibility, evidence_url=badge.evidence_url
        )
        if badge is not None
        else None,
    )


@router.get("/certificates/{certificate_id}/pdf", response_model=CertificatePdfResponse)
async def get_certificate_pdf(
    certificate_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> CertificatePdfResponse:
    certificate = await session.get(Certificate, _parse_uuid(certificate_id))
    if certificate is None or certificate.tenant_id != principal.tenant_id:
        raise NotFound("No such certificate.")
    if not await _owns_certificate(session, certificate, principal.user_id):
        principal.require("certificate:issue")
    if certificate.pdf_object_key is None:
        raise NotFound("This certificate has no PDF yet.")

    url = await storage.generate_signed_url(
        Container.GENERATED_DOCUMENTS, certificate.pdf_object_key, expires_in=300
    )
    return CertificatePdfResponse(pdf_url=url)


@router.get("/verify/{token}", response_model=VerificationResponse)
async def verify_credential(
    token: str,
    request: Request,
    tenant: TenantDep,
    session: SessionDep,
    redis: RedisDep,
    crypto: CryptoDep,
) -> VerificationResponse:
    ip = _client_ip(request)
    if ip is not None:
        ok = await rate_limit.hit(
            redis,
            key=f"ratelimit:verify:ip:{ip}",
            limit=VERIFY_RATE_LIMIT_PER_IP,
            window_seconds=VERIFY_RATE_LIMIT_WINDOW_SECONDS,
        )
        if not ok:
            raise TooManyAttempts("Too many attempts. Try again later.")

    result = await credentials_service.verify(
        session,
        crypto,
        tenant_id=tenant.id,
        raw_token=token,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return VerificationResponse(
        found=result.found,
        holder_name=result.holder_name,
        course_title=result.course_title,
        programme_title=result.course_title,
        issued_at=result.issued_at,
        expires_at=result.expires_at,
        status=result.status,
        credential_id=result.credential_id,
        issuer_name=result.issuer_name,
        cpd_points=result.cpd_points,
        visibility=result.visibility,
    )


@router.post("/certificates/{certificate_id}/revoke", response_model=CertificateResponse)
async def revoke_certificate(
    certificate_id: str,
    body: RevokeCertificateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> CertificateResponse:
    principal.require("certificate:revoke")
    certificate = await credentials_service.revoke(
        session,
        tenant_id=principal.tenant_id,
        certificate_id=_parse_uuid(certificate_id),
        reason=body.reason,
        revoker_user_id=principal.user_id,
    )
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.CERTIFICATE_REVOKED,
        actor_user_id=principal.user_id,
        entity_type="certificate",
        entity_id=certificate.id,
        after={"certificate_number": certificate.certificate_number, "reason": body.reason},
    )
    return CertificateResponse(
        id=str(certificate.id),
        certificate_number=certificate.certificate_number,
        status=certificate.status,
        visibility=certificate.visibility,
        issued_at=certificate.issued_at,
        revoked_reason=certificate.revoked_reason,
        pdf_available=certificate.pdf_object_key is not None,
    )


@router.patch("/certificates/{certificate_id}", response_model=CertificateResponse)
async def update_certificate_visibility(
    certificate_id: str, body: VisibilityRequest, principal: PrincipalDep, session: SessionDep
) -> CertificateResponse:
    certificate = await credentials_service.set_certificate_visibility(
        session,
        tenant_id=principal.tenant_id,
        certificate_id=_parse_uuid(certificate_id),
        user_id=principal.user_id,
        visibility=body.visibility,
    )
    return CertificateResponse(
        id=str(certificate.id),
        certificate_number=certificate.certificate_number,
        status=certificate.status,
        visibility=certificate.visibility,
        issued_at=certificate.issued_at,
        revoked_reason=certificate.revoked_reason,
        pdf_available=certificate.pdf_object_key is not None,
    )


@router.patch("/badges/{badge_id}", response_model=BadgeResponse)
async def update_badge_visibility(
    badge_id: str, body: VisibilityRequest, principal: PrincipalDep, session: SessionDep
) -> BadgeResponse:
    badge = await credentials_service.set_badge_visibility(
        session,
        tenant_id=principal.tenant_id,
        badge_id=_parse_uuid(badge_id),
        user_id=principal.user_id,
        visibility=body.visibility,
    )
    return BadgeResponse(
        id=str(badge.id), visibility=badge.visibility, evidence_url=badge.evidence_url
    )


@router.get("/badges/{badge_id}/share/linkedin", response_model=LinkedInShareResponse)
async def get_linkedin_share(
    badge_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    crypto: CryptoDep,
) -> LinkedInShareResponse:
    badge = await session.get(Badge, _parse_uuid(badge_id))
    if badge is None or badge.tenant_id != principal.tenant_id:
        raise NotFound("No such badge.")
    enrolment = await session.get(Enrolment, badge.enrolment_id)
    if enrolment is None or enrolment.user_id != principal.user_id:
        raise Forbidden("You do not have access to this badge.")
    if badge.certificate_id is None:
        raise NotFound("This badge has no linked certificate to share.")
    certificate = await session.get(Certificate, badge.certificate_id)
    if certificate is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such certificate.")

    url = credentials_service.verification_url(
        certificate, crypto, public_web_url=settings.public_web_url
    )
    fields = credentials_service.linkedin_share_fields(
        certificate=certificate, badge=badge, verification_url=url
    )
    return LinkedInShareResponse(**fields)


# --- Certificate/badge template authoring (Phase 4's authoring gap) -----
#
# `course:edit` gates writes here, not a template-specific permission —
# same reuse of the one content-authoring permission `routers/courses.py`
# and `routers/assessment.py` already apply across course/quiz/survey/
# assignment content. Templates are global, not tenant-scoped (same as
# `Course` itself), so there is no tenant filter on any of these.


def _certificate_template_response(template: CertificateTemplate) -> CertificateTemplateResponse:
    return CertificateTemplateResponse(
        id=str(template.id),
        title=template.title,
        issuer_name=template.issuer_name,
        signatory_name=template.signatory_name,
        signatory_title=template.signatory_title,
        cpd_points=template.cpd_points,
    )


def _badge_template_response(template: BadgeTemplate) -> BadgeTemplateResponse:
    return BadgeTemplateResponse(
        id=str(template.id),
        title=template.title,
        criteria=template.criteria,
        issuer_name=template.issuer_name,
        level=template.level,
    )


@router.post(
    "/certificate-templates",
    response_model=CertificateTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_certificate_template(
    body: CertificateTemplateCreateRequest, principal: PrincipalDep, session: SessionDep
) -> CertificateTemplateResponse:
    principal.require("course:edit")
    template = CertificateTemplate(
        id=uuid7(),
        title=body.title,
        issuer_name=body.issuer_name,
        signatory_name=body.signatory_name,
        signatory_title=body.signatory_title,
        cpd_points=body.cpd_points,
    )
    session.add(template)
    await session.flush()
    return _certificate_template_response(template)


@router.get("/certificate-templates", response_model=CertificateTemplatesPageResponse)
async def list_certificate_templates(
    principal: PrincipalDep, session: SessionDep
) -> CertificateTemplatesPageResponse:
    principal.require("course:view")
    stmt = select(CertificateTemplate).order_by(CertificateTemplate.title)
    templates = (await session.execute(stmt)).scalars().all()
    return CertificateTemplatesPageResponse(
        items=[_certificate_template_response(t) for t in templates]
    )


@router.patch("/certificate-templates/{template_id}", response_model=CertificateTemplateResponse)
async def update_certificate_template(
    template_id: str,
    body: CertificateTemplateUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> CertificateTemplateResponse:
    principal.require("course:edit")
    template = await session.get(CertificateTemplate, _parse_uuid(template_id))
    if template is None:
        raise NotFound("No such certificate template.")
    if body.title is not None:
        template.title = body.title
    if body.issuer_name is not None:
        template.issuer_name = body.issuer_name
    if body.signatory_name is not None:
        template.signatory_name = body.signatory_name
    if body.signatory_title is not None:
        template.signatory_title = body.signatory_title
    if body.cpd_points is not None:
        template.cpd_points = body.cpd_points
    await session.flush()
    return _certificate_template_response(template)


@router.post(
    "/badge-templates", response_model=BadgeTemplateResponse, status_code=status.HTTP_201_CREATED
)
async def create_badge_template(
    body: BadgeTemplateCreateRequest, principal: PrincipalDep, session: SessionDep
) -> BadgeTemplateResponse:
    principal.require("course:edit")
    template = BadgeTemplate(
        id=uuid7(),
        title=body.title,
        criteria=body.criteria,
        issuer_name=body.issuer_name,
        level=body.level,
    )
    session.add(template)
    await session.flush()
    return _badge_template_response(template)


@router.get("/badge-templates", response_model=BadgeTemplatesPageResponse)
async def list_badge_templates(
    principal: PrincipalDep, session: SessionDep
) -> BadgeTemplatesPageResponse:
    principal.require("course:view")
    stmt = select(BadgeTemplate).order_by(BadgeTemplate.title)
    templates = (await session.execute(stmt)).scalars().all()
    return BadgeTemplatesPageResponse(items=[_badge_template_response(t) for t in templates])


@router.patch("/badge-templates/{template_id}", response_model=BadgeTemplateResponse)
async def update_badge_template(
    template_id: str,
    body: BadgeTemplateUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> BadgeTemplateResponse:
    principal.require("course:edit")
    template = await session.get(BadgeTemplate, _parse_uuid(template_id))
    if template is None:
        raise NotFound("No such badge template.")
    if body.title is not None:
        template.title = body.title
    if body.criteria is not None:
        template.criteria = body.criteria
    if body.issuer_name is not None:
        template.issuer_name = body.issuer_name
    if body.level is not None:
        template.level = body.level
    await session.flush()
    return _badge_template_response(template)


__all__ = ["router"]
