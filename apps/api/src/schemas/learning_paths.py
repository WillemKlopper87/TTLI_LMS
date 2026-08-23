"""Request/response shapes for learning-path authoring and public
browsing (`routers/learning_paths.py`). Kept as its own module the same
way `schemas/course_wizard.py` is kept out of `schemas/courses.py`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.courses import PublicPrice


class LearningPathCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    slug: str | None = None
    description: str | None = None


class LearningPathUpdateRequest(BaseModel):
    """Every field `None` means "leave unchanged" — same convention as
    `CourseUpdateRequest`."""

    title: str | None = None
    description: str | None = None
    certificate_template_id: str | None = None


class LearningPathResponse(BaseModel):
    id: str
    slug: str
    title: str
    description: str | None
    state: str
    certificate_template_id: str | None


class LearningPathsPageResponse(BaseModel):
    items: list[LearningPathResponse]


class PathCourseRow(BaseModel):
    """A member course as it appears inside a path — enough to render
    the ordered list and add/remove UI, not the full `CourseResponse`."""

    course_id: str
    title: str
    slug: str
    state: str
    level: str | None
    position: int


class PathCoursesResponse(BaseModel):
    items: list[PathCourseRow]


class AddPathCourseRequest(BaseModel):
    course_id: str


class ReorderPathCoursesRequest(BaseModel):
    """Every member course id exactly once, in the desired order — same
    convention as `course_wizard.py`'s `ReorderRequest`."""

    ordered_course_ids: list[str] = Field(min_length=1)


class PathReadinessCheckRow(BaseModel):
    code: str
    level: str
    ok: bool
    message: str


class PathReadinessResponse(BaseModel):
    learning_path_id: str
    publishable: bool
    course_count: int
    checks: list[PathReadinessCheckRow]


class TenantAssignmentCreateRequest(BaseModel):
    is_bespoke: bool = False


class PathTenantAssignmentResponse(BaseModel):
    id: str
    tenant_id: str
    learning_path_id: str
    is_bespoke: bool


class PathTenantAssignmentRow(BaseModel):
    """`GET /tenant-path-assignments` — the path twin of courses.py's
    `TenantAssignmentRow` (F6, docs/research/p5-review-findings.md):
    drops `tenant_id`, since it's always the caller's own, and adds
    `learning_path_title` for display."""

    id: str
    learning_path_id: str
    learning_path_title: str
    is_bespoke: bool


class PathTenantAssignmentsPageResponse(BaseModel):
    items: list[PathTenantAssignmentRow]


class PublicPathCourseRow(BaseModel):
    course_id: str
    title: str
    summary: str | None
    level: str | None
    topic: str | None
    position: int


class PublicPathCard(BaseModel):
    id: str
    slug: str
    title: str
    description: str | None
    course_count: int
    has_certificate: bool
    price: PublicPrice | None


class PublicPathsResponse(BaseModel):
    items: list[PublicPathCard]


class PublicPathDetailResponse(BaseModel):
    id: str
    slug: str
    title: str
    description: str | None
    has_certificate: bool
    courses: list[PublicPathCourseRow]
    price: PublicPrice | None


class OwnPathEnrolmentResponse(BaseModel):
    """`GET /path-enrolments` — lightweight, no progress percentage, same
    split `OwnEnrolmentResponse`/`GET /enrolments` already draws against
    the heavier per-item progress endpoint."""

    path_enrolment_id: str
    learning_path_id: str
    learning_path_title: str
    course_count: int
    started_at: datetime
    completed_at: datetime | None
    has_certificate: bool


class PathCourseProgressRow(BaseModel):
    course_id: str
    course_title: str
    # None when the learner has no reachable enrolment for this member
    # course (F2, docs/research/p5-review-findings.md) — the frontend
    # renders the row with no "Continue" link rather than a dead one.
    enrolment_id: str | None
    progress_percent: int
    completed_at: datetime | None


class PathProgressResponse(BaseModel):
    path_enrolment_id: str
    learning_path_id: str
    progress_percent: int
    completed_at: datetime | None
    courses: list[PathCourseProgressRow]


__all__ = [
    "AddPathCourseRequest",
    "LearningPathCreateRequest",
    "LearningPathResponse",
    "LearningPathUpdateRequest",
    "LearningPathsPageResponse",
    "OwnPathEnrolmentResponse",
    "PathCourseProgressRow",
    "PathCourseRow",
    "PathCoursesResponse",
    "PathProgressResponse",
    "PathReadinessCheckRow",
    "PathReadinessResponse",
    "PathTenantAssignmentResponse",
    "PathTenantAssignmentRow",
    "PathTenantAssignmentsPageResponse",
    "PublicPathCard",
    "PublicPathCourseRow",
    "PublicPathDetailResponse",
    "PublicPathsResponse",
    "ReorderPathCoursesRequest",
    "TenantAssignmentCreateRequest",
]
