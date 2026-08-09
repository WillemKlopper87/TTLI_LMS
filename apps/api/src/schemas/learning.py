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


class LessonProgressResponse(BaseModel):
    lesson_id: str
    module_title: str
    title: str
    position: int
    activity_type: str
    video_asset_id: str | None
    state: str
    unmet_requirements: list[str]


class EnrolmentProgressResponse(BaseModel):
    enrolment_id: str
    course_id: str
    course_title: str
    lessons: list[LessonProgressResponse]


class LessonCompleteResponse(BaseModel):
    state: str
    next_lesson_id: str | None


class HeartbeatRequest(BaseModel):
    """03 §6.3. No timestamp field on purpose — REQ-BYPASS-02 means the
    server assigns it, so there is nothing here for a client to lie
    about."""

    position_seconds: Decimal = Field(ge=0)
    playback_rate: Decimal = Field(gt=0, default=Decimal("1.0"))
    session_id: str = Field(min_length=1, max_length=128)


class HeartbeatResponse(BaseModel):
    furthest_position_seconds: Decimal
    watched_seconds: Decimal


__all__ = [
    "EnrolmentProgressResponse",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "LessonCompleteResponse",
    "LessonProgressResponse",
    "OwnEnrolmentResponse",
]
