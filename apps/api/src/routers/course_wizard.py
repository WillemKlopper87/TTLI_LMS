"""Course-authoring wizard endpoints (`docs/research/course-authoring-
wizard.md` §2 — the small, additive backend surface the guided flow
needs). Same permission split `routers/courses.py` established:
`course:edit` for structure and content, and nothing here touches
publish/assign/pricing (those stay `course:publish`/`product:manage`
on their own routers — the wizard's later steps call them directly).

Registered *before* `routers/courses.py`'s parameterised routes would
matter only if a literal path here collided with one there; none do
(`/courses/{id}/outline|readiness|duplicate|clear-templates|modules/
reorder`, `/modules/{id}/lessons/reorder`, `/lessons/{id}/blocks[/{id}]`,
`/lessons/{id}/blocks/reorder`, `DELETE /modules/{id}`,
`DELETE /lessons/{id}`). Lesson-block CRUD/reorder lives here rather than
in `routers/courses.py` for the same reason lesson reorder/delete
already do — the guarded-delete and atomic-reorder shape, and avoiding
any path collision with `routers/courses.py`'s parameterised routes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import NotFound
from src.models.course import Lesson
from src.routers.courses import (
    _block_response,
    _course_response,
    _lesson_response,
    _module_response,
)
from src.schemas.course_wizard import (
    BlockOutlineRow,
    ClearTemplatesRequest,
    CourseOutlineResponse,
    DuplicateCourseRequest,
    LessonOutlineRow,
    ModuleOutlineRow,
    ReadinessCheckRow,
    ReadinessResponse,
    ReorderRequest,
)
from src.schemas.courses import (
    CourseResponse,
    LessonBlockCreateRequest,
    LessonBlockResponse,
    LessonBlocksPageResponse,
    LessonBlockUpdateRequest,
    LessonResponse,
    LessonsPageResponse,
    ModulesPageResponse,
)
from src.services import course_wizard as wizard
from src.services import courses as courses_service
from src.services import lesson_blocks as lesson_blocks_service

router = APIRouter(tags=["course-wizard"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


@router.get("/courses/{course_id}/outline", response_model=CourseOutlineResponse)
async def get_course_outline(
    course_id: str, principal: PrincipalDep, session: SessionDep
) -> CourseOutlineResponse:
    principal.require("course:edit")
    outline = await wizard.get_outline(
        session, course_id=_parse_uuid(course_id), tenant_id=principal.tenant_id
    )
    modules = [
        ModuleOutlineRow(
            module=_module_response(m.module),
            lessons=[
                LessonOutlineRow(
                    lesson=await _lesson_response(session, item.lesson),
                    blocks=[
                        BlockOutlineRow(
                            block=_block_response(b.block),
                            media_state=b.media_state,
                            duration_seconds=b.duration_seconds,
                            video_has_captions=b.video_has_captions,
                            question_count=b.question_count,
                            estimated_minutes=b.estimated_minutes,
                        )
                        for b in item.blocks
                    ],
                    estimated_minutes=item.estimated_minutes,
                )
                for item in m.lessons
            ],
        )
        for m in outline
    ]
    lessons = [item for m in outline for item in m.lessons]
    return CourseOutlineResponse(
        course_id=course_id,
        modules=modules,
        estimated_minutes=sum(item.estimated_minutes for item in lessons),
        lesson_count=len(lessons),
    )


@router.get("/courses/{course_id}/readiness", response_model=ReadinessResponse)
async def get_course_readiness(
    course_id: str, principal: PrincipalDep, session: SessionDep
) -> ReadinessResponse:
    principal.require("course:edit")
    report = await wizard.get_readiness(
        session, course_id=_parse_uuid(course_id), tenant_id=principal.tenant_id
    )
    return ReadinessResponse(
        course_id=course_id,
        publishable=report.publishable,
        score=report.score,
        estimated_minutes=report.estimated_minutes,
        module_count=report.module_count,
        lesson_count=report.lesson_count,
        checks=[
            ReadinessCheckRow(code=c.code, level=c.level, ok=c.ok, message=c.message)
            for c in report.checks
        ],
    )


@router.post(
    "/courses/{course_id}/duplicate",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_course(
    course_id: str, body: DuplicateCourseRequest, principal: PrincipalDep, session: SessionDep
) -> CourseResponse:
    principal.require("course:edit")
    copy = await wizard.duplicate_course(
        session, course_id=_parse_uuid(course_id), tenant_id=principal.tenant_id, title=body.title
    )
    return _course_response(copy)


@router.post("/courses/{course_id}/clear-templates", response_model=CourseResponse)
async def clear_course_templates(
    course_id: str, body: ClearTemplatesRequest, principal: PrincipalDep, session: SessionDep
) -> CourseResponse:
    principal.require("course:edit")
    course = await wizard.clear_course_templates(
        session,
        course_id=_parse_uuid(course_id),
        tenant_id=principal.tenant_id,
        certificate=body.certificate,
        badge=body.badge,
    )
    return _course_response(course)


@router.post("/courses/{course_id}/modules/reorder", response_model=ModulesPageResponse)
async def reorder_modules(
    course_id: str, body: ReorderRequest, principal: PrincipalDep, session: SessionDep
) -> ModulesPageResponse:
    principal.require("course:edit")
    modules = await wizard.reorder_modules(
        session,
        course_id=_parse_uuid(course_id),
        tenant_id=principal.tenant_id,
        ordered_ids=[_parse_uuid(x) for x in body.ordered_ids],
    )
    return ModulesPageResponse(items=[_module_response(m) for m in modules])


@router.post("/modules/{module_id}/lessons/reorder", response_model=LessonsPageResponse)
async def reorder_lessons(
    module_id: str, body: ReorderRequest, principal: PrincipalDep, session: SessionDep
) -> LessonsPageResponse:
    principal.require("course:edit")
    lessons = await wizard.reorder_lessons(
        session,
        module_id=_parse_uuid(module_id),
        tenant_id=principal.tenant_id,
        ordered_ids=[_parse_uuid(x) for x in body.ordered_ids],
    )
    return LessonsPageResponse(items=[await _lesson_response(session, x) for x in lessons])


@router.delete("/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_module(module_id: str, principal: PrincipalDep, session: SessionDep) -> None:
    principal.require("course:edit")
    await wizard.delete_module(
        session, module_id=_parse_uuid(module_id), tenant_id=principal.tenant_id
    )


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_lesson(lesson_id: str, principal: PrincipalDep, session: SessionDep) -> None:
    principal.require("course:edit")
    await wizard.delete_lesson(
        session, lesson_id=_parse_uuid(lesson_id), tenant_id=principal.tenant_id
    )


@router.get("/lessons/{lesson_id}", response_model=LessonResponse)
async def get_lesson(
    lesson_id: str, principal: PrincipalDep, session: SessionDep
) -> LessonResponse:
    """Author-side single-lesson read (`course:edit`) — what the draft
    "view as learner" preview falls back to when the public preview
    endpoint correctly refuses an unpublished/non-public lesson."""
    principal.require("course:edit")
    lesson = await session.get(Lesson, _parse_uuid(lesson_id))
    if lesson is None:
        raise NotFound("No such lesson.")
    course_id = await courses_service.resolve_course_id_for_module(
        session, module_id=lesson.module_id
    )
    await courses_service.assert_course_authorable(
        session, course_id=course_id, tenant_id=principal.tenant_id
    )
    return await _lesson_response(session, lesson)


# --- Lesson content blocks (0041) -----------------------------------------
#
# Replaces the old `DELETE /lessons/{id}/activity` (revert-to-document)
# endpoint — with a lesson able to hold any number of blocks, "detach"
# is just deleting the one block in question (delete_block below).


@router.post(
    "/lessons/{lesson_id}/blocks",
    response_model=LessonBlockResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_block(
    lesson_id: str, body: LessonBlockCreateRequest, principal: PrincipalDep, session: SessionDep
) -> LessonBlockResponse:
    principal.require("course:edit")
    block = await lesson_blocks_service.create_block(
        session,
        lesson_id=_parse_uuid(lesson_id),
        tenant_id=principal.tenant_id,
        block_type=body.block_type,
        completion_rules=body.completion_rules,
    )
    return _block_response(block)


@router.patch("/lessons/{lesson_id}/blocks/{block_id}", response_model=LessonBlockResponse)
async def update_block(
    lesson_id: str,
    block_id: str,
    body: LessonBlockUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> LessonBlockResponse:
    principal.require("course:edit")
    block = await lesson_blocks_service.update_block(
        session,
        block_id=_parse_uuid(block_id),
        tenant_id=principal.tenant_id,
        body=body.body,
        completion_rules=body.completion_rules,
    )
    return _block_response(block)


@router.post("/lessons/{lesson_id}/blocks/reorder", response_model=LessonBlocksPageResponse)
async def reorder_blocks(
    lesson_id: str, body: ReorderRequest, principal: PrincipalDep, session: SessionDep
) -> LessonBlocksPageResponse:
    principal.require("course:edit")
    blocks = await lesson_blocks_service.reorder_blocks(
        session,
        lesson_id=_parse_uuid(lesson_id),
        tenant_id=principal.tenant_id,
        ordered_ids=[_parse_uuid(x) for x in body.ordered_ids],
    )
    return LessonBlocksPageResponse(items=[_block_response(b) for b in blocks])


@router.delete(
    "/lessons/{lesson_id}/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_block(
    lesson_id: str, block_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("course:edit")
    await lesson_blocks_service.delete_block(
        session, block_id=_parse_uuid(block_id), tenant_id=principal.tenant_id
    )


__all__ = ["router"]
