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
from decimal import Decimal

from fastapi import APIRouter

from src.core.deps import CryptoDep, PrincipalDep, SessionDep, SettingsDep
from src.core.errors import NotFound
from src.schemas.learning import (
    EnrolmentProgressResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    LessonCompleteResponse,
    LessonProgressResponse,
    OwnEnrolmentResponse,
)
from src.services import enrolment as enrolment_service
from src.services import video_progress as video_progress_service

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
    enrolment_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> EnrolmentProgressResponse:
    enrolment, course, lessons = await enrolment_service.get_progress(
        session,
        crypto,
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
                video_asset_id=str(row.video_asset_id) if row.video_asset_id else None,
                quiz_id=str(row.quiz_id) if row.quiz_id else None,
                survey_id=str(row.survey_id) if row.survey_id else None,
                assignment_id=str(row.assignment_id) if row.assignment_id else None,
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
    lesson_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> LessonCompleteResponse:
    completion, next_lesson = await enrolment_service.complete_lesson(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        lesson_id=_parse_uuid(lesson_id),
    )
    return LessonCompleteResponse(
        state=completion.state,
        next_lesson_id=str(next_lesson.id) if next_lesson else None,
    )


@router.post(
    "/lessons/{lesson_id}/heartbeat",
    response_model=HeartbeatResponse,
    summary="Report real-time video-watch progress (REQ-BYPASS-02/03/04)",
)
async def record_heartbeat(
    lesson_id: str,
    body: HeartbeatRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> HeartbeatResponse:
    enrolment, _lesson = await enrolment_service.resolve_enrolment_for_lesson(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        lesson_id=_parse_uuid(lesson_id),
    )
    result = await video_progress_service.record_heartbeat(
        session,
        tenant_id=principal.tenant_id,
        enrolment_id=enrolment.id,
        lesson_id=_parse_uuid(lesson_id),
        position_seconds=body.position_seconds,
        playback_rate=body.playback_rate,
        session_id=body.session_id,
        max_playback_rate=Decimal(str(settings.heartbeat_max_playback_rate)),
    )
    return HeartbeatResponse(
        furthest_position_seconds=result.furthest_position_seconds,
        watched_seconds=result.watched_seconds,
    )


__all__ = ["router"]
