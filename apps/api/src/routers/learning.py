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

from src.core.deps import CryptoDep, PrincipalDep, SessionDep, SettingsDep, StorageDep
from src.core.errors import NotFound
from src.schemas.learning import (
    DashboardCertificate,
    DashboardEnrolment,
    DashboardNextLesson,
    DashboardResponse,
    DashboardStats,
    DashboardUpcoming,
    EnrolmentProgressResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    LessonCheckResponse,
    LessonCompleteResponse,
    LessonProgressResponse,
    OwnEnrolmentResponse,
    TranscriptLessonResponse,
    TranscriptResponse,
)
from src.services import dashboard as dashboard_service
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
    progress = await enrolment_service.get_progress(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        enrolment_id=_parse_uuid(enrolment_id),
    )
    return EnrolmentProgressResponse(
        enrolment_id=str(progress.enrolment.id),
        course_id=str(progress.course.id),
        course_title=progress.course.title,
        progress_percent=progress.progress_percent,
        next_lesson_id=str(progress.next_lesson_id) if progress.next_lesson_id else None,
        estimated_minutes=progress.estimated_minutes,
        lessons=[
            LessonProgressResponse(
                lesson_id=str(row.lesson_id),
                module_id=str(row.module_id),
                module_title=row.module_title,
                module_position=row.module_position,
                title=row.title,
                position=row.position,
                activity_type=row.activity_type,
                estimated_minutes=row.estimated_minutes,
                video_asset_id=str(row.video_asset_id) if row.video_asset_id else None,
                quiz_id=str(row.quiz_id) if row.quiz_id else None,
                survey_id=str(row.survey_id) if row.survey_id else None,
                assignment_id=str(row.assignment_id) if row.assignment_id else None,
                state=row.state,
                unmet_requirements=row.unmet_requirements,
                checks=[
                    LessonCheckResponse(
                        rule=check.rule,
                        met=check.met,
                        reason=check.reason,
                        current=check.current,
                        required=check.required,
                    )
                    for check in row.checks
                ],
            )
            for row in progress.lessons
        ],
    )


@router.get(
    "/learn/dashboard",
    response_model=DashboardResponse,
    summary="Everything the learner's signed-in landing screen renders",
)
async def get_dashboard(
    principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> DashboardResponse:
    board = await dashboard_service.get_dashboard(
        session, crypto, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    return DashboardResponse(
        first_name=board.first_name,
        initials=board.initials,
        enrolments=[
            DashboardEnrolment(
                enrolment_id=str(card.enrolment_id),
                course_id=str(card.course_id),
                course_title=card.course_title,
                hero_colour=card.hero_colour,
                status=card.status,
                progress_percent=card.progress_percent,
                lessons_total=card.lessons_total,
                lessons_completed=card.lessons_completed,
                next_lesson=DashboardNextLesson(
                    lesson_id=str(card.next_lesson.lesson_id),
                    title=card.next_lesson.title,
                    module_title=card.next_lesson.module_title,
                    position_label=card.next_lesson.position_label,
                )
                if card.next_lesson is not None
                else None,
                started_at=card.started_at,
                completed_at=card.completed_at,
                certificate=DashboardCertificate(
                    certificate_id=str(card.certificate.certificate_id),
                    certificate_number=card.certificate.certificate_number,
                    issued_at=card.certificate.issued_at,
                    status=card.certificate.status,
                )
                if card.certificate is not None
                else None,
            )
            for card in board.enrolments
        ],
        stats=DashboardStats(
            in_progress=board.stats.in_progress,
            completed=board.stats.completed,
            certificates=board.stats.certificates,
            workshop_credits=board.stats.workshop_credits,
        ),
        upcoming=[
            DashboardUpcoming(
                kind=item.kind,
                title=item.title,
                subtitle=item.subtitle,
                starts_at=item.starts_at,
                join_url=item.join_url,
                enrolment_id=str(item.enrolment_id) if item.enrolment_id else None,
                lesson_id=str(item.lesson_id) if item.lesson_id else None,
                quiz_id=str(item.quiz_id) if item.quiz_id else None,
                attempts_remaining=item.attempts_remaining,
            )
            for item in board.upcoming
        ],
    )


@router.get(
    "/enrolments/{enrolment_id}/transcript",
    response_model=TranscriptResponse,
    summary="A printable transcript of completed lessons (REQ-LMS-06)",
)
async def get_transcript(
    enrolment_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> TranscriptResponse:
    transcript = await enrolment_service.get_transcript(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        enrolment_id=_parse_uuid(enrolment_id),
    )
    return TranscriptResponse(
        learner_name=transcript.learner_name,
        course_title=transcript.course_title,
        enrolled_at=transcript.enrolled_at,
        completed_at=transcript.completed_at,
        certificate_number=transcript.certificate_number,
        lessons=[
            TranscriptLessonResponse(
                module_title=row.module_title,
                title=row.title,
                position=row.position,
                completed_at=row.completed_at,
            )
            for row in transcript.lessons
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
    lesson_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> LessonCompleteResponse:
    completion, next_lesson = await enrolment_service.complete_lesson(
        session,
        crypto,
        storage,
        settings,
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
    enrolment, lesson, course = await enrolment_service.resolve_enrolment_for_lesson(
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
    # Read back after the write, so the percentage the player renders is
    # the one this heartbeat just produced, not the previous one.
    video = await enrolment_service.video_context(
        session, lesson=lesson, course=course, enrolment_id=enrolment.id
    )
    return HeartbeatResponse(
        furthest_position_seconds=result.furthest_position_seconds,
        watched_seconds=result.watched_seconds,
        watched_percentage=video.watched_percentage,
        required_percentage=video.required_percentage,
        duration_seconds=video.duration_seconds,
    )


__all__ = ["router"]
