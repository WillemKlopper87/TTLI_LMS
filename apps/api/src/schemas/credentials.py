from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CertificatePdfResponse(BaseModel):
    pdf_url: str


class VerificationResponse(BaseModel):
    found: bool
    holder_name: str | None = None
    course_title: str | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    status: str | None = None


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


__all__ = [
    "BadgeResponse",
    "CertificatePdfResponse",
    "CertificateResponse",
    "EnrolmentCredentialsResponse",
    "LinkedInShareResponse",
    "RevokeCertificateRequest",
    "VerificationResponse",
    "VisibilityRequest",
]
