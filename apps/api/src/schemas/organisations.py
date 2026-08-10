from __future__ import annotations

from pydantic import BaseModel, Field


class CreateOrganisationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrganisationResponse(BaseModel):
    id: str
    name: str


class MemberResponse(BaseModel):
    user_id: str
    email: str
    relationship: str


class MembersResponse(BaseModel):
    items: list[MemberResponse]


class SeatSummaryResponse(BaseModel):
    course_id: str
    course_title: str
    purchased: int
    assigned: int
    available: int


class SeatSummariesResponse(BaseModel):
    items: list[SeatSummaryResponse]


class AssignedSeatResponse(BaseModel):
    entitlement_id: str
    user_id: str
    email: str
    granted_at: str


class AssignedSeatsResponse(BaseModel):
    items: list[AssignedSeatResponse]


class AssignSeatsRequest(BaseModel):
    course_id: str
    emails: list[str] = Field(min_length=1, max_length=200)


class SeatAssignmentResultResponse(BaseModel):
    email: str
    ok: bool
    reason: str | None


class AssignSeatsResponse(BaseModel):
    items: list[SeatAssignmentResultResponse]


__all__ = [
    "AssignSeatsRequest",
    "AssignSeatsResponse",
    "AssignedSeatResponse",
    "AssignedSeatsResponse",
    "CreateOrganisationRequest",
    "MemberResponse",
    "MembersResponse",
    "OrganisationResponse",
    "SeatAssignmentResultResponse",
    "SeatSummariesResponse",
    "SeatSummaryResponse",
]
