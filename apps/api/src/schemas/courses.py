from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.course import ACCESS_LEVEL_VALUES, MANAGER_VISIBILITY_VALUES


class UpdateManagerVisibilityRequest(BaseModel):
    manager_visibility: str = Field(pattern="^(" + "|".join(MANAGER_VISIBILITY_VALUES) + ")$")


class CourseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    description: str | None = None
    completion_rules: dict[str, object] = Field(default_factory=dict)


class CourseUpdateRequest(BaseModel):
    """Every field `None` means "leave unchanged" — clearing a
    certificate/badge template link back to null isn't supported here."""

    title: str | None = None
    description: str | None = None
    completion_rules: dict[str, object] | None = None
    certificate_template_id: str | None = None
    badge_template_id: str | None = None


class CourseResponse(BaseModel):
    id: str
    slug: str
    title: str
    description: str | None
    state: str
    manager_visibility: str
    completion_rules: dict[str, object]
    certificate_template_id: str | None
    badge_template_id: str | None


class CoursesPageResponse(BaseModel):
    items: list[CourseResponse]


class ModuleCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ModuleUpdateRequest(BaseModel):
    title: str | None = None
    position: int | None = Field(default=None, ge=0)


class ModuleResponse(BaseModel):
    id: str
    course_id: str
    title: str
    position: int


class ModulesPageResponse(BaseModel):
    items: list[ModuleResponse]


class LessonCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    access_level: str = Field(default="paid", pattern="^(" + "|".join(ACCESS_LEVEL_VALUES) + ")$")
    body: str | None = None
    completion_rules: dict[str, object] = Field(default_factory=dict)


class LessonUpdateRequest(BaseModel):
    """No `activity_type`/`quiz_id`/`survey_id`/`assignment_id`/
    `video_asset_id` field on purpose — those stay owned by
    `POST /lessons/{id}/quiz|survey|assignment|video`."""

    title: str | None = None
    access_level: str | None = Field(
        default=None, pattern="^(" + "|".join(ACCESS_LEVEL_VALUES) + ")$"
    )
    body: str | None = None
    completion_rules: dict[str, object] | None = None
    position: int | None = Field(default=None, ge=0)


class LessonResponse(BaseModel):
    id: str
    module_id: str
    title: str
    position: int
    activity_type: str
    access_level: str
    body: str | None
    completion_rules: dict[str, object]
    video_asset_id: str | None
    quiz_id: str | None
    survey_id: str | None
    assignment_id: str | None


class LessonsPageResponse(BaseModel):
    items: list[LessonResponse]


class TenantAssignmentCreateRequest(BaseModel):
    is_bespoke: bool = False


class TenantAssignmentResponse(BaseModel):
    id: str
    tenant_id: str
    course_id: str
    is_bespoke: bool


class TenantAssignmentRow(BaseModel):
    id: str
    course_id: str
    course_title: str
    is_bespoke: bool


class TenantAssignmentsPageResponse(BaseModel):
    items: list[TenantAssignmentRow]


__all__ = [
    "CourseCreateRequest",
    "CourseResponse",
    "CourseUpdateRequest",
    "CoursesPageResponse",
    "LessonCreateRequest",
    "LessonResponse",
    "LessonUpdateRequest",
    "LessonsPageResponse",
    "ModuleCreateRequest",
    "ModuleResponse",
    "ModuleUpdateRequest",
    "ModulesPageResponse",
    "TenantAssignmentCreateRequest",
    "TenantAssignmentResponse",
    "TenantAssignmentRow",
    "TenantAssignmentsPageResponse",
    "UpdateManagerVisibilityRequest",
]
