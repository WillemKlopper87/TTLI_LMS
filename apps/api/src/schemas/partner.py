"""Partner portal request/response schemas (2026-09-11-partner-portal-design.md)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class PartnerProfileCreateRequest(BaseModel):
    """Request to create a partner profile."""

    organisation_id: uuid.UUID = Field(..., description="Organisation ID for the partner")
    display_name: str = Field(..., min_length=1, max_length=500, description="Display name")
    bio: str | None = Field(None, max_length=2000, description="Partner bio/description")
    logo_object_key: str | None = Field(None, description="S3 object key for partner logo")
    professional_body: str | None = Field(
        None, max_length=500, description="Professional body for health professionals"
    )


class PartnerProfileResponse(BaseModel):
    """Response containing partner profile data."""

    id: uuid.UUID
    organisation_id: uuid.UUID
    display_name: str
    bio: str | None = None
    logo_object_key: str | None = None
    professional_body: str | None = None
    status: str
    operator_agreement_accepted_at: str | None = None


class ActivationStatusResponse(BaseModel):
    """Response indicating whether a partner can be activated and why."""

    can_activate: bool
    missing_gates: list[str] = Field(default_factory=list)


class CreateClientOrgRequest(BaseModel):
    """Request to create a client organisation under a partner."""

    name: str = Field(..., min_length=1, max_length=500, description="Client organisation name")


class ClientOrgResponse(BaseModel):
    """Response containing created client organisation."""

    id: uuid.UUID
    name: str
    kind: str
    parent_organisation_id: uuid.UUID | None = None
