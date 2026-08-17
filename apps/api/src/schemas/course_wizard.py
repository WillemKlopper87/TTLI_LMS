"""Request/response shapes for the course-authoring wizard endpoints
(`routers/course_wizard.py`). Kept out of `schemas/courses.py` the same
way the service is kept out of `services/courses.py`."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.schemas.courses import LessonResponse, ModuleResponse


class ReorderRequest(BaseModel):
    """Every sibling id exactly once, in the desired order."""

    ordered_ids: list[str] = Field(min_length=1)


class ClearTemplatesRequest(BaseModel):
    certificate: bool = False
    badge: bool = False


class DuplicateCourseRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class LessonOutlineRow(BaseModel):
    lesson: LessonResponse
    video_state: str | None
    video_duration_seconds: int | None
    video_has_captions: bool
    question_count: int | None
    estimated_minutes: int


class ModuleOutlineRow(BaseModel):
    module: ModuleResponse
    lessons: list[LessonOutlineRow]


class CourseOutlineResponse(BaseModel):
    course_id: str
    modules: list[ModuleOutlineRow]
    estimated_minutes: int
    lesson_count: int


class ReadinessCheckRow(BaseModel):
    code: str
    level: str
    ok: bool
    message: str


class ReadinessResponse(BaseModel):
    course_id: str
    publishable: bool
    score: int
    estimated_minutes: int
    module_count: int
    lesson_count: int
    checks: list[ReadinessCheckRow]


__all__ = [
    "ClearTemplatesRequest",
    "CourseOutlineResponse",
    "DuplicateCourseRequest",
    "LessonOutlineRow",
    "ModuleOutlineRow",
    "ReadinessCheckRow",
    "ReadinessResponse",
    "ReorderRequest",
]
