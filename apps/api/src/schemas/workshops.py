from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.workshop import ATTENDANCE_STATUS_VALUES, SESSION_TYPE_VALUES


class CreateFacilitatorRequest(BaseModel):
    email: str
    bio: str | None = None


class FacilitatorResponse(BaseModel):
    id: str
    user_id: str
    email: str
    bio: str | None
    timezone: str


class FacilitatorsPage(BaseModel):
    items: list[FacilitatorResponse]


class AddAvailabilityRequest(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")


class AvailabilityWindowResponse(BaseModel):
    id: str
    day_of_week: int
    start_time: str
    end_time: str


class AvailabilityPage(BaseModel):
    items: list[AvailabilityWindowResponse]


class CreateWorkshopRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    session_type: str = Field(pattern="^(" + "|".join(SESSION_TYPE_VALUES) + ")$")
    default_duration_minutes: int = Field(default=60, ge=15, le=480)


class WorkshopResponse(BaseModel):
    id: str
    title: str
    description: str | None
    session_type: str
    default_duration_minutes: int


class WorkshopsPage(BaseModel):
    items: list[WorkshopResponse]


class CreateSessionRequest(BaseModel):
    facilitator_id: str
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(ge=1, le=500)


class SessionResponse(BaseModel):
    id: str
    workshop_id: str
    facilitator_id: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    status: str
    registered: int
    waitlisted: int


class SessionsPage(BaseModel):
    items: list[SessionResponse]


class BookingResponse(BaseModel):
    id: str
    session_id: str
    user_id: str
    status: str
    join_url: str | None


class MarkAttendanceRequest(BaseModel):
    user_id: str
    status: str = Field(pattern="^(" + "|".join(ATTENDANCE_STATUS_VALUES) + ")$")


class RosterRowResponse(BaseModel):
    booking_id: str
    user_id: str
    email: str
    booking_status: str
    attendance_status: str


class RosterResponse(BaseModel):
    items: list[RosterRowResponse]


__all__ = [
    "AddAvailabilityRequest",
    "AvailabilityPage",
    "AvailabilityWindowResponse",
    "BookingResponse",
    "CreateFacilitatorRequest",
    "CreateSessionRequest",
    "CreateWorkshopRequest",
    "FacilitatorResponse",
    "FacilitatorsPage",
    "MarkAttendanceRequest",
    "RosterResponse",
    "RosterRowResponse",
    "SessionResponse",
    "SessionsPage",
    "WorkshopResponse",
    "WorkshopsPage",
]
