from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CertificatePdfResponse(BaseModel):
    pdf_url: str


class VerificationResponse(BaseModel):
    """What the public `/verify/{token}` page renders. Every field is null
    on a miss — and a `private` certificate is deliberately a miss (see
    services/credentials.py::verify), so none of the additions here can
    leak a credential the holder chose not to publish.

    `programme_title` is an alias of `course_title`, not a second fact:
    the verify page speaks the customer's vocabulary ("programme") while
    the rest of the API speaks the data model's ("course")."""

    found: bool
    holder_name: str | None = None
    course_title: str | None = None
    programme_title: str | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    status: str | None = None
    credential_id: str | None = None
    issuer_name: str | None = None
    cpd_points: int | None = None
    visibility: str | None = None


class RevokeCertificateRequest(BaseModel):
    reason: str = Field(min_length=1)


class CertificateResponse(BaseModel):
    id: str
    certificate_number: str
    status: str
    visibility: str
    issued_at: datetime
    revoked_reason: str | None = None
    pdf_available: bool = False


class VisibilityRequest(BaseModel):
    """Shared by `PATCH /certificates/{id}` and `PATCH /badges/{id}` —
    REQ-CRED-07 gives the learner the same three-way control over both."""

    visibility: str = Field(pattern="^(private|public|link_only)$")


class BadgeResponse(BaseModel):
    id: str
    visibility: str
    evidence_url: str | None = None


class LinkedInShareResponse(BaseModel):
    share_url: str
    add_to_profile_url: str
    credential_id: str
    credential_url: str


class EnrolmentCredentialsResponse(BaseModel):
    """`GET /enrolments/{id}/credentials` — how a learner's own client
    discovers the certificate/badge IDs it needs for every other endpoint
    in this file. Both null until the completion rule engine issues them
    (services/enrolment.py::complete_lesson), which is the normal state
    for any course still in progress."""

    certificate: CertificateResponse | None = None
    badge: BadgeResponse | None = None


class CertificateTemplateCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    issuer_name: str = Field(min_length=1)
    signatory_name: str = Field(min_length=1)
    signatory_title: str = Field(min_length=1)
    cpd_points: int | None = None


class CertificateTemplateUpdateRequest(BaseModel):
    title: str | None = None
    issuer_name: str | None = None
    signatory_name: str | None = None
    signatory_title: str | None = None
    cpd_points: int | None = None


class CertificateTemplateResponse(BaseModel):
    id: str
    title: str
    issuer_name: str
    signatory_name: str
    signatory_title: str
    cpd_points: int | None = None


class CertificateTemplatesPageResponse(BaseModel):
    items: list[CertificateTemplateResponse]


class BadgeTemplateCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    criteria: str = Field(min_length=1)
    issuer_name: str = Field(min_length=1)
    level: str | None = None


class BadgeTemplateUpdateRequest(BaseModel):
    title: str | None = None
    criteria: str | None = None
    issuer_name: str | None = None
    level: str | None = None


class BadgeTemplateResponse(BaseModel):
    id: str
    title: str
    criteria: str
    issuer_name: str
    level: str | None = None


class BadgeTemplatesPageResponse(BaseModel):
    items: list[BadgeTemplateResponse]


__all__ = [
    "BadgeResponse",
    "BadgeTemplateCreateRequest",
    "BadgeTemplateResponse",
    "BadgeTemplateUpdateRequest",
    "BadgeTemplatesPageResponse",
    "CertificatePdfResponse",
    "CertificateResponse",
    "CertificateTemplateCreateRequest",
    "CertificateTemplateResponse",
    "CertificateTemplateUpdateRequest",
    "CertificateTemplatesPageResponse",
    "EnrolmentCredentialsResponse",
    "LinkedInShareResponse",
    "RevokeCertificateRequest",
    "VerificationResponse",
    "VisibilityRequest",
]
