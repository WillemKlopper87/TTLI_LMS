"""Learning and progression (03 §6, REQ-BYPASS-01/02/10/11).

Every endpoint here is gated on the caller owning the enrolment — this is
a learner acting on their own progress, the same buyer-facing ownership
pattern routers/orders.py uses for orders. There is no admin override
endpoint yet (no content-author or facilitator surface exists this
sprint); adding one later must not weaken this ownership check for the
learner-facing routes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import NotFound
from src.schemas.learning import (
    EnrolmentProgressResponse,
    LessonCompleteResponse,
    LessonProgressResponse,
    OwnEnrolmentResponse,
)
from src.services import enrolment as enrolment_service

router = APIRouter(tags=["learning"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


@router.get(
    "/enrolments",
    response_model=list[OwnEnrolmentResponse],
    summary="The caller's own enrolments",
)
async def list_own_enrolments(
    principal: PrincipalDep, session: SessionDep
) -> list[OwnEnrolmentResponse]:
    rows = await enrolment_service.list_own_enrolments(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    return [
        OwnEnrolmentResponse(
            enrolment_id=str(row.enrolment_id),
            course_id=str(row.course_id),
            course_title=row.course_title,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )
        for row in rows
    ]


@router.get(
    "/enrolments/{enrolment_id}/progress",
    response_model=EnrolmentProgressResponse,
    summary="Per-lesson progress for one of the caller's enrolments",
)
async def get_progress(
    enrolment_id: str, principal: PrincipalDep, session: SessionDep
) -> EnrolmentProgressResponse:
    enrolment, course, lessons = await enrolment_service.get_progress(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        enrolment_id=_parse_uuid(enrolment_id),
    )
    return EnrolmentProgressResponse(
        enrolment_id=str(enrolment.id),
        course_id=str(course.id),
        course_title=course.title,
        lessons=[
            LessonProgressResponse(
                lesson_id=str(row.lesson_id),
                module_title=row.module_title,
                title=row.title,
                position=row.position,
                activity_type=row.activity_type,
                state=row.state,
                unmet_requirements=row.unmet_requirements,
            )
            for row in lessons
        ],
    )


@router.post(
    "/lessons/{lesson_id}/start",
    status_code=204,
    response_model=None,
    summary="Start a lesson (idempotent)",
)
async def start_lesson(lesson_id: str, principal: PrincipalDep, session: SessionDep) -> None:
    await enrolment_service.start_lesson(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        lesson_id=_parse_uuid(lesson_id),
    )


@router.post(
    "/lessons/{lesson_id}/complete",
    response_model=LessonCompleteResponse,
    summary="Complete a lesson — the server-side rule engine decides, not the caller",
)
async def complete_lesson(
    lesson_id: str, principal: PrincipalDep, session: SessionDep
) -> LessonCompleteResponse:
    completion, next_lesson = await enrolment_service.complete_lesson(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        lesson_id=_parse_uuid(lesson_id),
    )
    return LessonCompleteResponse(
        state=completion.state,
        next_lesson_id=str(next_lesson.id) if next_lesson else None,
    )


__all__ = ["router"]
