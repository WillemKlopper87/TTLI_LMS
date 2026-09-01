from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.course import (
    ACCESS_LEVEL_VALUES,
    COURSE_FORMAT_VALUES,
    COURSE_LEVEL_VALUES,
    MANAGER_VISIBILITY_VALUES,
)

_LEVEL_PATTERN = "^(" + "|".join(COURSE_LEVEL_VALUES) + ")$"
_FORMAT_PATTERN = "^(" + "|".join(COURSE_FORMAT_VALUES) + ")$"
_HEX_COLOUR_PATTERN = "^#[0-9A-Fa-f]{6}$"


class UpdateManagerVisibilityRequest(BaseModel):
    manager_visibility: str = Field(pattern="^(" + "|".join(MANAGER_VISIBILITY_VALUES) + ")$")


class UpdateVideoSettingsRequest(BaseModel):
    # Partial/nullable (0040): omitting a field leaves it untouched;
    # sending it as null clears that key back to "inherit the tenant
    # default" (services/media/video_settings.py's fallback chain).
    rungs: list[str] | None = None
    allow_bypass: bool | None = None


class CourseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    description: str | None = None
    completion_rules: dict[str, object] = Field(default_factory=dict)
    # 0029 presentation metadata — all optional.
    summary: str | None = None
    level: str | None = Field(default=None, pattern=_LEVEL_PATTERN)
    topic: str | None = Field(default=None, max_length=64)
    format: str | None = Field(default=None, pattern=_FORMAT_PATTERN)
    outcomes: list[str] | None = None
    includes_workshop: bool | None = None
    hero_colour: str | None = Field(default=None, pattern=_HEX_COLOUR_PATTERN)


class CourseUpdateRequest(BaseModel):
    """Every field `None` means "leave unchanged" — clearing a
    certificate/badge template link back to null isn't supported here."""

    title: str | None = None
    description: str | None = None
    completion_rules: dict[str, object] | None = None
    certificate_template_id: str | None = None
    badge_template_id: str | None = None
    summary: str | None = None
    level: str | None = Field(default=None, pattern=_LEVEL_PATTERN)
    topic: str | None = Field(default=None, max_length=64)
    format: str | None = Field(default=None, pattern=_FORMAT_PATTERN)
    outcomes: list[str] | None = None
    includes_workshop: bool | None = None
    hero_colour: str | None = Field(default=None, pattern=_HEX_COLOUR_PATTERN)


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
    summary: str | None = None
    level: str | None = None
    topic: str | None = None
    format: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    includes_workshop: bool = False
    hero_colour: str | None = None
    video_settings: dict[str, object] = Field(default_factory=dict)


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


class PublicLessonRow(BaseModel):
    """No `body`/quiz/survey/assignment/video FKs — an anonymous curriculum
    view shows shape, not content (services/courses.py::get_public_curriculum)."""

    id: str
    title: str
    position: int
    activity_type: str
    access_level: str
    estimated_minutes: int = 0
    # access_level == "public" — the lesson a visitor can open before buying.
    is_preview: bool = False


class PublicModuleRow(BaseModel):
    id: str
    title: str
    position: int
    lessons: list[PublicLessonRow]
    estimated_minutes: int = 0
    lesson_count: int = 0


class PublicPrice(BaseModel):
    """The first active, priced product selling this course to *this*
    tenant — what the catalogue card / detail page's price block shows.
    Mirrors `schemas/commerce.py::PriceSummary` (`unit_amount` as a
    string so no float rounding on the wire) plus the product it hangs
    off, so "Enrol" can go straight to `POST /orders`."""

    product_id: str
    price_id: str
    currency: str
    unit_amount: str
    tax_behaviour: str
    # tax_behaviour == "inclusive" — the displayed amount already
    # contains VAT; "exclusive" means the checkout adds it.
    includes_vat: bool


class PublicCourseCard(BaseModel):
    """One row of `GET /public/courses` — the catalogue/landing grid.
    Every facet the prototype filters on (topic / format / includes /
    level) is here so the client can compute counts itself."""

    id: str
    slug: str
    title: str
    summary: str | None
    description: str | None
    level: str | None
    topic: str | None
    format: str | None
    outcomes: list[str]
    includes_workshop: bool
    has_certificate: bool
    cpd_points: int | None
    estimated_minutes: int
    module_count: int
    lesson_count: int
    hero_colour: str | None
    price: PublicPrice | None


class PublicCoursesResponse(BaseModel):
    items: list[PublicCourseCard]


class PublicCurriculumResponse(BaseModel):
    course_id: str
    title: str
    description: str | None
    modules: list[PublicModuleRow]
    summary: str | None = None
    level: str | None = None
    topic: str | None = None
    format: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    includes_workshop: bool = False
    has_certificate: bool = False
    cpd_points: int | None = None
    estimated_minutes: int = 0
    lesson_count: int = 0
    hero_colour: str | None = None
    price: PublicPrice | None = None


class PublicLessonPreviewResponse(BaseModel):
    id: str
    title: str
    activity_type: str
    body: str | None
    video_asset_id: str | None
    quiz_id: str | None
    survey_id: str | None
    assignment_id: str | None


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
    "PublicCourseCard",
    "PublicCoursesResponse",
    "PublicCurriculumResponse",
    "PublicLessonPreviewResponse",
    "PublicLessonRow",
    "PublicModuleRow",
    "PublicPrice",
    "TenantAssignmentCreateRequest",
    "TenantAssignmentResponse",
    "TenantAssignmentRow",
    "TenantAssignmentsPageResponse",
    "UpdateManagerVisibilityRequest",
    "UpdateVideoSettingsRequest",
]
