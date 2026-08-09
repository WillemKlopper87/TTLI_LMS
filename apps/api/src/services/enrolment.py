"""Enrolments and lesson progression (02 §7, 03 §6, REQ-BYPASS-01/02/10/11).

An enrolment is created once, at order fulfilment
(services/orders.py::approve_eft), never independently here — this module
only reads enrolments and writes lesson_completions.

Prerequisite enforcement (REQ-BYPASS-10) is a strict linear chain by
`(module.position, lesson.position)` for this sprint — drip-release dates
and cohort/self-paced modes (REQ-LMS-02) are not built yet (02 §13 lists
cohort definition as an open question). A lesson_completions row exists
only once a learner has actually started it; 'locked'/'available' for
lessons with no row are computed on read, never eagerly materialised.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import Forbidden, LessonLocked, NotFound
from src.core.ids import uuid7
from src.models.audit import AuditAction
from src.models.course import Course, Lesson, Module
from src.models.learning import Enrolment, LessonCompletion
from src.models.media import VideoAsset
from src.services import audit
from src.services import video_progress as video_progress_service
from src.services.completion import evaluate, merge_rules


@dataclass(frozen=True, slots=True)
class OrderedLesson:
    lesson: Lesson
    module: Module


@dataclass(frozen=True, slots=True)
class OwnEnrolmentRow:
    enrolment_id: uuid.UUID
    course_id: uuid.UUID
    course_title: str
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class LessonProgressRow:
    lesson_id: uuid.UUID
    module_title: str
    title: str
    position: int
    activity_type: str
    video_asset_id: uuid.UUID | None
    state: str
    unmet_requirements: list[str]


async def _ordered_lessons(session: AsyncSession, course_id: uuid.UUID) -> list[OrderedLesson]:
    stmt = (
        select(Lesson, Module)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course_id)
        .order_by(Module.position, Lesson.position)
    )
    rows = (await session.execute(stmt)).all()
    return [OrderedLesson(lesson=lesson, module=module) for lesson, module in rows]


async def _get_lesson_and_course(
    session: AsyncSession, lesson_id: uuid.UUID
) -> tuple[Lesson, Course]:
    stmt = (
        select(Lesson, Course)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(Lesson.id == lesson_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFound("No such lesson.")
    return row[0], row[1]


async def has_access_to_video(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, video_asset_id: uuid.UUID
) -> bool:
    """03 §6.7's entitlement check, run before a playback URL is ever
    minted — a video is reachable only through a lesson, whose course the
    caller must hold a real enrolment for."""
    course_ids_stmt = (
        select(Course.id)
        .join(Module, Module.course_id == Course.id)
        .join(Lesson, Lesson.module_id == Module.id)
        .where(Lesson.video_asset_id == video_asset_id)
    )
    course_ids = (await session.execute(course_ids_stmt)).scalars().all()
    if not course_ids:
        return False

    enrolment_stmt = select(Enrolment.id).where(
        Enrolment.tenant_id == tenant_id,
        Enrolment.user_id == user_id,
        Enrolment.course_id.in_(course_ids),
    )
    return (await session.execute(enrolment_stmt)).first() is not None


async def get_or_create_enrolment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    entitlement_id: uuid.UUID,
) -> Enrolment:
    """Called from services/orders.py::approve_eft, in the same transaction
    as the entitlement grant (02 §6.2) — get-or-create because a learner
    buying the same course a second time (e.g. after their first
    entitlement expired) must not violate the one-enrolment-per-course
    unique constraint."""
    stmt = select(Enrolment).where(
        Enrolment.tenant_id == tenant_id,
        Enrolment.user_id == user_id,
        Enrolment.course_id == course_id,
    )
    enrolment = (await session.execute(stmt)).scalar_one_or_none()
    if enrolment is not None:
        return enrolment

    enrolment = Enrolment(
        id=uuid7(),
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        entitlement_id=entitlement_id,
    )
    session.add(enrolment)
    await session.flush()
    return enrolment


async def list_own_enrolments(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> list[OwnEnrolmentRow]:
    """REQ-LMS-03's "resume where you left off" needs some way for a
    learner to find their own enrolments in the first place — this is
    that discovery list, not an admin surface (no pagination/filters:
    a personal list is small by construction)."""
    stmt = (
        select(Enrolment, Course)
        .join(Course, Course.id == Enrolment.course_id)
        .where(Enrolment.tenant_id == tenant_id, Enrolment.user_id == user_id)
        .order_by(Enrolment.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        OwnEnrolmentRow(
            enrolment_id=enrolment.id,
            course_id=course.id,
            course_title=course.title,
            started_at=enrolment.started_at,
            completed_at=enrolment.completed_at,
        )
        for enrolment, course in rows
    ]


async def get_own_enrolment(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> Enrolment:
    stmt = select(Enrolment).where(
        Enrolment.tenant_id == tenant_id,
        Enrolment.user_id == user_id,
        Enrolment.course_id == course_id,
    )
    enrolment = (await session.execute(stmt)).scalar_one_or_none()
    if enrolment is None:
        raise Forbidden("You are not enrolled in this course.")
    return enrolment


async def _get_own_enrolment_by_id(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, enrolment_id: uuid.UUID
) -> Enrolment:
    enrolment = await session.get(Enrolment, enrolment_id)
    if enrolment is None or enrolment.tenant_id != tenant_id:
        raise NotFound("No such enrolment.")
    if enrolment.user_id != user_id:
        raise Forbidden("You do not have access to this enrolment.")
    return enrolment


async def _existing_completion(
    session: AsyncSession, *, enrolment_id: uuid.UUID, lesson_id: uuid.UUID
) -> LessonCompletion | None:
    stmt = select(LessonCompletion).where(
        LessonCompletion.enrolment_id == enrolment_id, LessonCompletion.lesson_id == lesson_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _next_lesson(
    session: AsyncSession, *, course_id: uuid.UUID, current_lesson_id: uuid.UUID
) -> Lesson | None:
    ordered = await _ordered_lessons(session, course_id)
    ids = [item.lesson.id for item in ordered]
    idx = ids.index(current_lesson_id)
    if idx + 1 < len(ids):
        return ordered[idx + 1].lesson
    return None


async def _video_watch_percentage(
    session: AsyncSession, *, lesson: Lesson, enrolment_id: uuid.UUID
) -> float | None:
    if lesson.video_asset_id is None:
        return None
    video_asset = await session.get(VideoAsset, lesson.video_asset_id)
    if video_asset is None or video_asset.duration_seconds is None:
        return None
    return await video_progress_service.watch_percentage(
        session,
        enrolment_id=enrolment_id,
        lesson_id=lesson.id,
        duration_seconds=video_asset.duration_seconds,
    )


async def resolve_enrolment_for_lesson(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> tuple[Enrolment, Lesson]:
    """The ownership resolution `start_lesson`/`complete_lesson` each do
    inline, factored out for `POST /lessons/{id}/heartbeat`
    (routers/learning.py) too."""
    lesson, course = await _get_lesson_and_course(session, lesson_id)
    enrolment = await get_own_enrolment(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
    )
    return enrolment, lesson


async def start_lesson(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> LessonCompletion:
    """Idempotent (03 §6.2) — records first_seen_at once, on the first call."""
    lesson, course = await _get_lesson_and_course(session, lesson_id)
    enrolment = await get_own_enrolment(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
    )

    completion = await _existing_completion(session, enrolment_id=enrolment.id, lesson_id=lesson.id)
    if completion is not None:
        return completion

    completion = LessonCompletion(
        id=uuid7(),
        tenant_id=tenant_id,
        enrolment_id=enrolment.id,
        lesson_id=lesson.id,
        state="in_progress",
    )
    session.add(completion)
    if enrolment.started_at is None:
        enrolment.started_at = datetime.now(UTC)
    await session.flush()
    return completion


async def complete_lesson(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> tuple[LessonCompletion, Lesson | None]:
    """03 §6.4 — runs the merged rule set server-side; the client's opinion
    is never consulted (REQ-BYPASS-01). Returns the completed row plus the
    next lesson in sequence, if any (None means the course is done —
    sound under this sprint's strict-linear locking, since reaching the
    last lesson implies every prior one was already completed)."""
    lesson, course = await _get_lesson_and_course(session, lesson_id)
    enrolment = await get_own_enrolment(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
    )

    completion = await _existing_completion(session, enrolment_id=enrolment.id, lesson_id=lesson.id)
    if completion is None:
        raise LessonLocked("Start the lesson before completing it.")
    if completion.state == "completed":
        return completion, await _next_lesson(
            session, course_id=course.id, current_lesson_id=lesson.id
        )

    rules = merge_rules(course.completion_rules, lesson.completion_rules)
    watched_pct = await _video_watch_percentage(session, lesson=lesson, enrolment_id=enrolment.id)
    result = evaluate(
        rules, first_seen_at=completion.first_seen_at, video_watched_percentage=watched_pct
    )
    completion.rule_evaluation = result.as_json()

    if not result.met:
        await audit.record(
            session,
            tenant_id=tenant_id,
            action=AuditAction.LESSON_COMPLETION_REFUSED,
            actor_user_id=user_id,
            entity_type="lesson",
            entity_id=lesson.id,
            after=result.as_json(),
        )
        await session.flush()
        raise LessonLocked(
            "This lesson's requirements are not met yet.",
            {"checks": result.as_json()["checks"]},
        )

    completion.state = "completed"
    completion.completed_at = datetime.now(UTC)
    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.LESSON_COMPLETED,
        actor_user_id=user_id,
        entity_type="lesson",
        entity_id=lesson.id,
        after=result.as_json(),
    )

    next_lesson = await _next_lesson(session, course_id=course.id, current_lesson_id=lesson.id)
    if next_lesson is None:
        enrolment.completed_at = datetime.now(UTC)
    await session.flush()
    return completion, next_lesson


async def get_progress(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, enrolment_id: uuid.UUID
) -> tuple[Enrolment, Course, list[LessonProgressRow]]:
    """03 §6.1 — the UI renders its checklist from `unmet_requirements`; it
    does not compute it."""
    enrolment = await _get_own_enrolment_by_id(
        session, tenant_id=tenant_id, user_id=user_id, enrolment_id=enrolment_id
    )
    course = await session.get(Course, enrolment.course_id)
    if course is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such course.")

    ordered = await _ordered_lessons(session, course.id)
    completions_stmt = select(LessonCompletion).where(LessonCompletion.enrolment_id == enrolment.id)
    completions = {c.lesson_id: c for c in (await session.execute(completions_stmt)).scalars()}

    rows: list[LessonProgressRow] = []
    previous_completed = True
    for item in ordered:
        lesson = item.lesson
        completion = completions.get(lesson.id)
        unmet: list[str] = []

        if completion is not None:
            state = completion.state
            if state != "completed":
                rules = merge_rules(course.completion_rules, lesson.completion_rules)
                watched_pct = await _video_watch_percentage(
                    session, lesson=lesson, enrolment_id=enrolment.id
                )
                result = evaluate(
                    rules,
                    first_seen_at=completion.first_seen_at,
                    video_watched_percentage=watched_pct,
                )
                unmet = [c.reason for c in result.checks if not c.met]
        elif previous_completed:
            state = "available"
        else:
            state = "locked"
            unmet = ["Complete the previous lesson first."]

        rows.append(
            LessonProgressRow(
                lesson_id=lesson.id,
                module_title=item.module.title,
                title=lesson.title,
                position=lesson.position,
                activity_type=lesson.activity_type,
                video_asset_id=lesson.video_asset_id,
                state=state,
                unmet_requirements=unmet,
            )
        )
        previous_completed = state == "completed"

    return enrolment, course, rows


__all__ = [
    "LessonProgressRow",
    "OwnEnrolmentRow",
    "complete_lesson",
    "get_or_create_enrolment",
    "get_own_enrolment",
    "get_progress",
    "has_access_to_video",
    "list_own_enrolments",
    "resolve_enrolment_for_lesson",
    "start_lesson",
]
