"""Course/module/lesson authoring, and tenant-visibility assignment
(02 §5, REQ-TEN-03). Business logic lives in `src/services/courses.py`
— this file is routing, permission checks, and response construction
only, matching the split `src/routers/workshops.py` uses.

`course:edit` gates every write here, the same permission
`src/routers/assessment.py`'s quiz/survey/assignment creation already
reuses — this codebase treats "content authoring" as one permission
across subsystems rather than a `course:*`/`quiz:*`/`lesson:*` permission
per resource type. `course:publish` is narrower: publishing, unpublishing,
and assigning a course to a tenant all change what a course *makes
visible or purchasable*, not just its content.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import NotFound
from src.models.course import Course, Lesson, Module
from src.schemas.courses import (
    CourseCreateRequest,
    CourseResponse,
    CoursesPageResponse,
    CourseUpdateRequest,
    LessonCreateRequest,
    LessonResponse,
    LessonsPageResponse,
    LessonUpdateRequest,
    ModuleCreateRequest,
    ModuleResponse,
    ModulesPageResponse,
    ModuleUpdateRequest,
    TenantAssignmentCreateRequest,
    TenantAssignmentResponse,
    TenantAssignmentRow,
    TenantAssignmentsPageResponse,
    UpdateManagerVisibilityRequest,
)
from src.services import courses as courses_service

router = APIRouter(tags=["courses"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


def _course_response(course: Course) -> CourseResponse:
    return CourseResponse(
        id=str(course.id),
        slug=course.slug,
        title=course.title,
        description=course.description,
        state=course.state,
        manager_visibility=course.manager_visibility,
        completion_rules=course.completion_rules,
        certificate_template_id=(
            str(course.certificate_template_id) if course.certificate_template_id else None
        ),
        badge_template_id=str(course.badge_template_id) if course.badge_template_id else None,
    )


def _module_response(module: Module) -> ModuleResponse:
    return ModuleResponse(
        id=str(module.id),
        course_id=str(module.course_id),
        title=module.title,
        position=module.position,
    )


def _lesson_response(lesson: Lesson) -> LessonResponse:
    return LessonResponse(
        id=str(lesson.id),
        module_id=str(lesson.module_id),
        title=lesson.title,
        position=lesson.position,
        activity_type=lesson.activity_type,
        access_level=lesson.access_level,
        body=lesson.body,
        completion_rules=lesson.completion_rules,
        video_asset_id=str(lesson.video_asset_id) if lesson.video_asset_id else None,
        quiz_id=str(lesson.quiz_id) if lesson.quiz_id else None,
        survey_id=str(lesson.survey_id) if lesson.survey_id else None,
        assignment_id=str(lesson.assignment_id) if lesson.assignment_id else None,
    )


@router.get("/courses", response_model=CoursesPageResponse)
async def list_courses(principal: PrincipalDep, session: SessionDep) -> CoursesPageResponse:
    principal.require("course:view")
    courses = (await session.execute(select(Course).order_by(Course.title))).scalars().all()
    return CoursesPageResponse(items=[_course_response(c) for c in courses])


@router.post("/courses", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CourseCreateRequest, principal: PrincipalDep, session: SessionDep
) -> CourseResponse:
    principal.require("course:edit")
    course = await courses_service.create_course(
        session,
        title=body.title,
        slug=body.slug,
        description=body.description,
        completion_rules=body.completion_rules,
    )
    return _course_response(course)


@router.get("/courses/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: str, principal: PrincipalDep, session: SessionDep
) -> CourseResponse:
    principal.require("course:view")
    course = await courses_service.get_course(session, course_id=_parse_uuid(course_id))
    return _course_response(course)


@router.patch("/courses/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: str, body: CourseUpdateRequest, principal: PrincipalDep, session: SessionDep
) -> CourseResponse:
    principal.require("course:edit")
    course = await courses_service.update_course(
        session,
        course_id=_parse_uuid(course_id),
        title=body.title,
        description=body.description,
        completion_rules=body.completion_rules,
        certificate_template_id=(
            _parse_uuid(body.certificate_template_id) if body.certificate_template_id else None
        ),
        badge_template_id=_parse_uuid(body.badge_template_id) if body.badge_template_id else None,
    )
    return _course_response(course)


@router.patch("/courses/{course_id}/manager-visibility", response_model=CourseResponse)
async def update_manager_visibility(
    course_id: str,
    body: UpdateManagerVisibilityRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> CourseResponse:
    principal.require("course:edit")
    course = await session.get(Course, _parse_uuid(course_id))
    if course is None:
        raise NotFound("No such course.")
    course.manager_visibility = body.manager_visibility
    await session.flush()
    return _course_response(course)


@router.post("/courses/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: str, principal: PrincipalDep, session: SessionDep
) -> CourseResponse:
    principal.require("course:publish")
    course = await courses_service.publish_course(session, course_id=_parse_uuid(course_id))
    return _course_response(course)


@router.post("/courses/{course_id}/unpublish", response_model=CourseResponse)
async def unpublish_course(
    course_id: str, principal: PrincipalDep, session: SessionDep
) -> CourseResponse:
    principal.require("course:publish")
    course = await courses_service.unpublish_course(session, course_id=_parse_uuid(course_id))
    return _course_response(course)


@router.post(
    "/courses/{course_id}/modules",
    response_model=ModuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_module(
    course_id: str, body: ModuleCreateRequest, principal: PrincipalDep, session: SessionDep
) -> ModuleResponse:
    principal.require("course:edit")
    module = await courses_service.create_module(
        session, course_id=_parse_uuid(course_id), title=body.title
    )
    return _module_response(module)


@router.get("/courses/{course_id}/modules", response_model=ModulesPageResponse)
async def list_modules(
    course_id: str, principal: PrincipalDep, session: SessionDep
) -> ModulesPageResponse:
    principal.require("course:view")
    modules = await courses_service.list_modules(session, course_id=_parse_uuid(course_id))
    return ModulesPageResponse(items=[_module_response(m) for m in modules])


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
async def update_module(
    module_id: str, body: ModuleUpdateRequest, principal: PrincipalDep, session: SessionDep
) -> ModuleResponse:
    principal.require("course:edit")
    module = await courses_service.update_module(
        session, module_id=_parse_uuid(module_id), title=body.title, position=body.position
    )
    return _module_response(module)


@router.post(
    "/modules/{module_id}/lessons",
    response_model=LessonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lesson(
    module_id: str, body: LessonCreateRequest, principal: PrincipalDep, session: SessionDep
) -> LessonResponse:
    principal.require("course:edit")
    lesson = await courses_service.create_lesson(
        session,
        module_id=_parse_uuid(module_id),
        title=body.title,
        access_level=body.access_level,
        body=body.body,
        completion_rules=body.completion_rules,
    )
    return _lesson_response(lesson)


@router.get("/modules/{module_id}/lessons", response_model=LessonsPageResponse)
async def list_lessons(
    module_id: str, principal: PrincipalDep, session: SessionDep
) -> LessonsPageResponse:
    principal.require("course:view")
    lessons = await courses_service.list_lessons(session, module_id=_parse_uuid(module_id))
    return LessonsPageResponse(items=[_lesson_response(lesson) for lesson in lessons])


@router.patch("/lessons/{lesson_id}", response_model=LessonResponse)
async def update_lesson(
    lesson_id: str, body: LessonUpdateRequest, principal: PrincipalDep, session: SessionDep
) -> LessonResponse:
    principal.require("course:edit")
    lesson = await courses_service.update_lesson(
        session,
        lesson_id=_parse_uuid(lesson_id),
        title=body.title,
        access_level=body.access_level,
        body=body.body,
        completion_rules=body.completion_rules,
        position=body.position,
    )
    return _lesson_response(lesson)


@router.post(
    "/courses/{course_id}/tenant-assignments",
    response_model=TenantAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_course_to_tenant(
    course_id: str,
    body: TenantAssignmentCreateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> TenantAssignmentResponse:
    principal.require("course:publish")
    assignment = await courses_service.assign_course_to_tenant(
        session,
        course_id=_parse_uuid(course_id),
        tenant_id=principal.tenant_id,
        is_bespoke=body.is_bespoke,
    )
    return TenantAssignmentResponse(
        id=str(assignment.id),
        tenant_id=str(assignment.tenant_id),
        course_id=str(assignment.course_id),
        is_bespoke=assignment.is_bespoke,
    )


@router.get("/tenant-assignments", response_model=TenantAssignmentsPageResponse)
async def list_tenant_assignments(
    principal: PrincipalDep, session: SessionDep
) -> TenantAssignmentsPageResponse:
    principal.require("course:view")
    rows = await courses_service.list_tenant_assignments(session, tenant_id=principal.tenant_id)
    return TenantAssignmentsPageResponse(
        items=[
            TenantAssignmentRow(
                id=str(assignment.id),
                course_id=str(course.id),
                course_title=course.title,
                is_bespoke=assignment.is_bespoke,
            )
            for assignment, course in rows
        ]
    )


__all__ = ["router"]
