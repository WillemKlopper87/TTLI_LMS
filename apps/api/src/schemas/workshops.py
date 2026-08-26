from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

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


class CoachingFacilitatorResponse(BaseModel):
    """The deliberately small facilitator profile learners may see.

    Email and user_id stay on the administrative `FacilitatorResponse`;
    neither is needed to choose a coach.
    """

    id: str
    display_name: str
    bio: str | None
    timezone: str


class CoachingFacilitatorsPage(BaseModel):
    items: list[CoachingFacilitatorResponse]


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
    requires_credit: bool
    meeting_provider: str


class WorkshopsPage(BaseModel):
    items: list[WorkshopResponse]
    # P7 phase 5: whether the platform-wide Teams credentials
    # (`Settings.graph_*`) are set — carried on the list response so the
    # admin UI's provider selector can warn before an admin picks
    # "teams" on a workshop and only discovers it 400s at booking time.
    teams_configured: bool
    # P13 phase 4: same warning, for `Settings.zoom_*`.
    zoom_configured: bool
    # P13 phase 5: same warning, for `Settings.google_*`.
    meet_configured: bool


class UpdateWorkshopRequest(BaseModel):
    """Both optional — a PATCH only ever sends the one field its own
    control changed (the credit-gate checkbox, Phase 4; the provider
    selector, Phase 5), never a full resend of workshop state."""

    requires_credit: bool | None = None
    # "manual"/"teams"/"zoom"/"meet" are the four real providers
    # (`services/meeting/__init__.py::get_provider`) — every value in
    # the DB enum now has an implemented client.
    meeting_provider: str | None = Field(default=None, pattern="^(manual|teams|zoom|meet)$")


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


class CancelSessionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AddSessionFacilitatorRequest(BaseModel):
    facilitator_id: str


class PublicSessionRow(BaseModel):
    """A bookable session as an anonymous visitor may see it: when it
    runs, who leads it and whether seats remain. Deliberately no
    `join_url` and no roster — those belong to a learner who has booked
    (`POST /sessions/{id}/book` returns the join link)."""

    session_id: str
    workshop_id: str
    title: str
    description: str | None
    session_type: str
    facilitator_name: str | None
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    capacity: int
    seats_left: int
    is_full: bool


class PublicOneOnOneWorkshopRow(BaseModel):
    """A self-service coaching workshop as an anonymous visitor may see
    it — unlike `PublicSessionRow`, there is no pre-created session to
    describe; a visitor who wants to book picks a facilitator and a
    slot on `/workshops/{id}/book`."""

    id: str
    title: str
    description: str | None
    default_duration_minutes: int


class PublicWorkshopsResponse(BaseModel):
    items: list[PublicSessionRow]
    one_on_one_workshops: list[PublicOneOnOneWorkshopRow] = Field(default_factory=list)


class OpenSlotRow(BaseModel):
    starts_at: datetime
    ends_at: datetime


class OpenSlotsPage(BaseModel):
    items: list[OpenSlotRow]


class BookOpenSlotRequest(BaseModel):
    facilitator_id: str
    starts_at: datetime

    @field_validator("starts_at")
    @classmethod
    def starts_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("starts_at must include a timezone offset")
        return value


class BookingResponse(BaseModel):
    id: str
    session_id: str
    user_id: str
    status: str
    join_url: str | None


class RescheduleBookingRequest(BaseModel):
    target_session_id: str


class OwnBookingResponse(BaseModel):
    """`GET /bookings` — the learner's own "my sessions" page (P7):
    what a booking's own workflow (cancel/reschedule) needs, unlike the
    admin/facilitator-oriented `GET /workshops/{id}/sessions`."""

    booking_id: str
    session_id: str
    workshop_id: str
    workshop_title: str
    facilitator_names: list[str]
    starts_at: datetime
    ends_at: datetime
    status: str
    session_status: str
    join_url: str | None
    provider: str | None
    can_manage: bool


class OwnBookingsPage(BaseModel):
    items: list[OwnBookingResponse]


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
    "AddSessionFacilitatorRequest",
    "AvailabilityPage",
    "AvailabilityWindowResponse",
    "BookOpenSlotRequest",
    "BookingResponse",
    "CancelSessionRequest",
    "CoachingFacilitatorResponse",
    "CoachingFacilitatorsPage",
    "CreateFacilitatorRequest",
    "CreateSessionRequest",
    "CreateWorkshopRequest",
    "FacilitatorResponse",
    "FacilitatorsPage",
    "MarkAttendanceRequest",
    "OpenSlotRow",
    "OpenSlotsPage",
    "OwnBookingResponse",
    "OwnBookingsPage",
    "PublicOneOnOneWorkshopRow",
    "PublicSessionRow",
    "PublicWorkshopsResponse",
    "RescheduleBookingRequest",
    "RosterResponse",
    "RosterRowResponse",
    "SessionResponse",
    "SessionsPage",
    "UpdateWorkshopRequest",
    "WorkshopResponse",
    "WorkshopsPage",
]
