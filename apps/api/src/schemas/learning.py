from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


__all__ = [
    "EnrolmentProgressResponse",
    "LessonCompleteResponse",
    "LessonProgressResponse",
    "OwnEnrolmentResponse",
]
