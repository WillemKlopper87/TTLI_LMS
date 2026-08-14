"""Course/module/lesson authoring, and tenant visibility assignment
(02 §5, the Phase 4 authoring gap `docs/STATUS.md` tracked). `Course` is
global, not tenant-scoped (`src/models/course.py`'s own docstring);
`CourseTenantAssignment` is what makes an authored course visible to a
given tenant, and only a published course may be assigned.

`activity_type` and the quiz/survey/assignment/video FKs on `Lesson` stay
owned by their own subsystems' attach endpoints
(`src/routers/assessment.py`, `src/routers/media.py`) — nothing here ever
sets them; a lesson created through this module is always a plain
"document" lesson until one of those endpoints attaches real content.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.course import Course, CourseTenantAssignment, Lesson, Module
from src.models.credential import BadgeTemplate, CertificateTemplate
from src.services.completion import CompletionRules

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class CourseAuthoringError(AppError):
    """A refusal in the authoring flow — an empty course can't publish,
    an unpublished course can't be assigned to a tenant, or a
    completion_rules value doesn't validate."""

    code = "COURSE_AUTHORING_ERROR"


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "course"


async def _unique_slug(session: AsyncSession, title: str) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while (
        await session.execute(select(Course.id).where(Course.slug == slug))
    ).scalar_one_or_none() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _validate_completion_rules(rules: dict[str, object]) -> dict[str, object]:
    try:
        CompletionRules.model_validate(rules)
    except Exception as exc:
        raise CourseAuthoringError(f"Invalid completion_rules: {exc}") from exc
    return rules


async def create_course(
    session: AsyncSession,
    *,
    title: str,
    slug: str | None,
    description: str | None,
    completion_rules: dict[str, object],
) -> Course:
    _validate_completion_rules(completion_rules)
    course = Course(
        id=uuid7(),
        slug=slug or await _unique_slug(session, title),
        title=title,
        description=description,
        completion_rules=completion_rules,
    )
    session.add(course)
    await session.flush()
    return course


async def get_course(session: AsyncSession, *, course_id: uuid.UUID) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFound("No such course.")
    return course


async def list_courses(session: AsyncSession) -> list[Course]:
    stmt = select(Course).order_by(Course.title)
    return list((await session.execute(stmt)).scalars().all())


async def update_course(
    session: AsyncSession,
    *,
    course_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    completion_rules: dict[str, object] | None = None,
    certificate_template_id: uuid.UUID | None = None,
    badge_template_id: uuid.UUID | None = None,
) -> Course:
    course = await get_course(session, course_id=course_id)
    if title is not None:
        course.title = title
    if description is not None:
        course.description = description
    if completion_rules is not None:
        course.completion_rules = _validate_completion_rules(completion_rules)
    if certificate_template_id is not None:
        if await session.get(CertificateTemplate, certificate_template_id) is None:
            raise NotFound("No such certificate template.")
        course.certificate_template_id = certificate_template_id
    if badge_template_id is not None:
        if await session.get(BadgeTemplate, badge_template_id) is None:
            raise NotFound("No such badge template.")
        course.badge_template_id = badge_template_id
    await session.flush()
    return course


async def publish_course(session: AsyncSession, *, course_id: uuid.UUID) -> Course:
    course = await get_course(session, course_id=course_id)
    modules = await list_modules(session, course_id=course_id)
    if not modules:
        raise CourseAuthoringError("A course needs at least one module before it can be published.")
    for module in modules:
        if not await list_lessons(session, module_id=module.id):
            raise CourseAuthoringError(
                f'Module "{module.title}" has no lessons — every module needs at least one.'
            )
    course.state = "published"
    await session.flush()
    return course


async def unpublish_course(session: AsyncSession, *, course_id: uuid.UUID) -> Course:
    course = await get_course(session, course_id=course_id)
    course.state = "draft"
    await session.flush()
    return course


async def create_module(session: AsyncSession, *, course_id: uuid.UUID, title: str) -> Module:
    await get_course(session, course_id=course_id)
    position = (
        await session.execute(
            select(func.count()).select_from(Module).where(Module.course_id == course_id)
        )
    ).scalar_one()
    module = Module(id=uuid7(), course_id=course_id, title=title, position=position)
    session.add(module)
    await session.flush()
    return module


async def update_module(
    session: AsyncSession,
    *,
    module_id: uuid.UUID,
    title: str | None = None,
    position: int | None = None,
) -> Module:
    module = await session.get(Module, module_id)
    if module is None:
        raise NotFound("No such module.")
    if title is not None:
        module.title = title
    if position is not None:
        module.position = position
    await session.flush()
    return module


async def list_modules(session: AsyncSession, *, course_id: uuid.UUID) -> list[Module]:
    stmt = select(Module).where(Module.course_id == course_id).order_by(Module.position)
    return list((await session.execute(stmt)).scalars().all())


async def create_lesson(
    session: AsyncSession,
    *,
    module_id: uuid.UUID,
    title: str,
    access_level: str = "paid",
    body: str | None = None,
    completion_rules: dict[str, object] | None = None,
) -> Lesson:
    module = await session.get(Module, module_id)
    if module is None:
        raise NotFound("No such module.")
    rules = _validate_completion_rules(completion_rules or {})
    position = (
        await session.execute(
            select(func.count()).select_from(Lesson).where(Lesson.module_id == module_id)
        )
    ).scalar_one()
    lesson = Lesson(
        id=uuid7(),
        module_id=module_id,
        title=title,
        position=position,
        activity_type="document",
        access_level=access_level,
        body=body,
        completion_rules=rules,
    )
    session.add(lesson)
    await session.flush()
    return lesson


async def update_lesson(
    session: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    title: str | None = None,
    access_level: str | None = None,
    body: str | None = None,
    completion_rules: dict[str, object] | None = None,
    position: int | None = None,
) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFound("No such lesson.")
    if title is not None:
        lesson.title = title
    if access_level is not None:
        lesson.access_level = access_level
    if body is not None:
        lesson.body = body
    if completion_rules is not None:
        lesson.completion_rules = _validate_completion_rules(completion_rules)
    if position is not None:
        lesson.position = position
    await session.flush()
    return lesson


async def list_lessons(session: AsyncSession, *, module_id: uuid.UUID) -> list[Lesson]:
    stmt = select(Lesson).where(Lesson.module_id == module_id).order_by(Lesson.position)
    return list((await session.execute(stmt)).scalars().all())


async def assign_course_to_tenant(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID, is_bespoke: bool
) -> CourseTenantAssignment:
    course = await get_course(session, course_id=course_id)
    if course.state != "published":
        raise CourseAuthoringError("Only a published course may be assigned to a tenant.")

    existing = (
        await session.execute(
            select(CourseTenantAssignment).where(
                CourseTenantAssignment.tenant_id == tenant_id,
                CourseTenantAssignment.course_id == course_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_bespoke = is_bespoke
        await session.flush()
        return existing

    assignment = CourseTenantAssignment(
        id=uuid7(), tenant_id=tenant_id, course_id=course_id, is_bespoke=is_bespoke
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def list_tenant_assignments(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[tuple[CourseTenantAssignment, Course]]:
    stmt = (
        select(CourseTenantAssignment, Course)
        .join(Course, Course.id == CourseTenantAssignment.course_id)
        .where(CourseTenantAssignment.tenant_id == tenant_id)
        .order_by(Course.title)
    )
    return list((await session.execute(stmt)).tuples().all())


__all__ = [
    "CourseAuthoringError",
    "assign_course_to_tenant",
    "create_course",
    "create_lesson",
    "create_module",
    "get_course",
    "list_courses",
    "list_lessons",
    "list_modules",
    "list_tenant_assignments",
    "publish_course",
    "unpublish_course",
    "update_course",
    "update_lesson",
    "update_module",
]
