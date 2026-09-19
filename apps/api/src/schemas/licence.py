"""Request and response schemas for licensing operations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateLicenceRequest(BaseModel):
    """Request to create a new licence."""

    organisation_id: str = Field(description="UUID of the licensee organisation")
    course_id: str | None = Field(
        default=None, description="UUID of the course (XOR with learning_path_id)"
    )
    learning_path_id: str | None = Field(
        default=None, description="UUID of the learning path (XOR with course_id)"
    )
    seats_purchased: int = Field(gt=0, description="Number of seats purchased")
    starts_at: datetime
    ends_at: datetime
    price_per_seat_cents: int | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    royalty_pct: float | None = None
    order_id: str | None = None
    notes: str | None = None


class LicenceResponse(BaseModel):
    """Response representing a licence."""

    id: str
    organisation_id: str
    course_id: str | None
    learning_path_id: str | None
    status: str
    seats_purchased: int
    seats_used: int
    starts_at: str  # ISO 8601
    ends_at: str  # ISO 8601
    price_per_seat_cents: int | None
    currency: str | None
    royalty_pct: float | None
    order_id: str | None
    notes: str | None
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601


class ListLicencesResponse(BaseModel):
    """Response containing a list of licences."""

    items: list[LicenceResponse]


class GrantSeatRequest(BaseModel):
    """Request to grant a seat under a licence to a learner.

    No client-supplied entitlement_id: grant_seat always derives a real
    Entitlement itself from the licence, the same way a course purchase
    or corporate seat assignment does — accepting one from the caller
    would let a client link a seat grant to an entitlement it has no
    provenance for.
    """

    licence_id: str = Field(description="UUID of the licence")
    learner_user_id: str = Field(description="UUID of the learner")


class SeatGrantResponse(BaseModel):
    """Response representing a seat grant."""

    id: str
    licence_id: str
    learner_user_id: str
    entitlement_id: str | None
    granted_at: str  # ISO 8601
    revoked_at: str | None  # ISO 8601


class ListSeatGrantsResponse(BaseModel):
    """Response containing seat grants for a licensee."""

    items: list[SeatGrantResponse]


__all__ = [
    "CreateLicenceRequest",
    "GrantSeatRequest",
    "LicenceResponse",
    "ListLicencesResponse",
    "ListSeatGrantsResponse",
    "SeatGrantResponse",
]
