from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class OwnEnrolmentResponse(BaseModel):
    enrolment_id: str
    course_id: str
    course_title: str
    started_at: datetime | None
    completed_at: datetime | None


class LessonCheckResponse(BaseModel):
    """One completion rule, met or not. `unmet_requirements` stays the
    flat refusal-reason list it always was; this is the full checklist —
    cleared rules included — with a short pair of display values
    ("41%" / "80%", "5:19" / "10:00") where a rule has numbers worth
    showing, and nulls where it does not."""

    rule: str
    met: bool
    reason: str
    current: str | None = None
    required: str | None = None


class LessonProgressResponse(BaseModel):
    lesson_id: str
    module_id: str
    module_title: str
    module_position: int
    title: str
    position: int
    activity_type: str
    estimated_minutes: int
    video_asset_id: str | None
    quiz_id: str | None
    survey_id: str | None
    assignment_id: str | None
    state: str
    unmet_requirements: list[str]
    checks: list[LessonCheckResponse] = Field(default_factory=list)


class EnrolmentProgressResponse(BaseModel):
    enrolment_id: str
    course_id: str
    course_title: str
    lessons: list[LessonProgressResponse]
    progress_percent: int = 0
    next_lesson_id: str | None = None
    estimated_minutes: int = 0


class LessonCompleteResponse(BaseModel):
    state: str
    next_lesson_id: str | None


class TranscriptLessonResponse(BaseModel):
    module_title: str
    title: str
    position: int
    completed_at: datetime | None


class TranscriptResponse(BaseModel):
    """REQ-LMS-06: a printable transcript — apps/web renders this as a
    print-optimised page, not a PDF; the data is what needs to be
    correct, not a particular file format."""

    learner_name: str
    course_title: str
    enrolled_at: datetime
    completed_at: datetime | None
    certificate_number: str | None
    lessons: list[TranscriptLessonResponse]


class HeartbeatRequest(BaseModel):
    """03 §6.3. No timestamp field on purpose — REQ-BYPASS-02 means the
    server assigns it, so there is nothing here for a client to lie
    about."""

    position_seconds: Decimal = Field(ge=0)
    playback_rate: Decimal = Field(gt=0, default=Decimal("1.0"))
    session_id: str = Field(min_length=1, max_length=128)


class HeartbeatResponse(BaseModel):
    """The raw counters, plus what the player's progress ring needs to
    render the completion rule it is being measured against without a
    second round trip. All three additions are null when the lesson has
    no video asset, no known duration, or no watch-percentage rule."""

    furthest_position_seconds: Decimal
    watched_seconds: Decimal
    watched_percentage: int | None = None
    required_percentage: int | None = None
    duration_seconds: int | None = None


# --- The learner dashboard (`GET /learn/dashboard`) ----------------------


class DashboardNextLesson(BaseModel):
    lesson_id: str
    title: str
    module_title: str
    position_label: str


class DashboardCertificate(BaseModel):
    certificate_id: str
    certificate_number: str
    issued_at: datetime
    status: str


class DashboardEnrolment(BaseModel):
    enrolment_id: str
    course_id: str
    course_title: str
    hero_colour: str | None = None
    status: str
    progress_percent: int
    lessons_total: int
    lessons_completed: int
    next_lesson: DashboardNextLesson | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    certificate: DashboardCertificate | None = None


class DashboardStats(BaseModel):
    in_progress: int
    completed: int
    certificates: int
    workshop_credits: int


class DashboardUpcoming(BaseModel):
    """A workshop session the learner is registered for, or an assessment
    sitting open in a course they are part-way through. One shape for
    both, because the dashboard renders them in one list."""

    kind: str
    title: str
    subtitle: str
    starts_at: datetime | None = None
    join_url: str | None = None
    provider: str | None = None
    enrolment_id: str | None = None
    lesson_id: str | None = None
    quiz_id: str | None = None
    attempts_remaining: int | None = None


class DashboardResponse(BaseModel):
    first_name: str | None = None
    initials: str
    enrolments: list[DashboardEnrolment] = Field(default_factory=list)
    stats: DashboardStats
    upcoming: list[DashboardUpcoming] = Field(default_factory=list)


__all__ = [
    "DashboardCertificate",
    "DashboardEnrolment",
    "DashboardNextLesson",
    "DashboardResponse",
    "DashboardStats",
    "DashboardUpcoming",
    "EnrolmentProgressResponse",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "LessonCheckResponse",
    "LessonCompleteResponse",
    "LessonProgressResponse",
    "OwnEnrolmentResponse",
    "TranscriptLessonResponse",
    "TranscriptResponse",
]
