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
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from src.core.config import Settings
from src.core.crypto import CryptoBox
from src.core.errors import Forbidden, LessonLocked, NotFound
from src.core.ids import uuid7
from src.models.assessment import Assignment, AssignmentSubmission, QuizAttempt, Survey
from src.models.audit import AuditAction
from src.models.course import Course, Lesson, LessonBlock, Module
from src.models.credential import Certificate
from src.models.learning import Enrolment, LessonCompletion
from src.models.learning_path import LearningPath
from src.models.media import VideoAsset
from src.models.user import User
from src.services import audit, course_wizard, entitlements, identity
from src.services import credentials as credentials_service
from src.services import lesson_blocks as lesson_blocks_service
from src.services import survey as survey_service
from src.services import video_progress as video_progress_service
from src.services.completion import CompletionRules, evaluate, merge_rules
from src.services.storage import Container, StorageService


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
class LessonCheckRow:
    """One completion rule as the learner-facing checklist renders it —
    met *and* unmet alike, unlike `unmet_requirements`, which stays a
    flat list of refusal reasons. `current`/`required` are short display
    strings ("41%" / "80%", "5:19" / "10:00") or null for a rule with
    nothing meaningful to show a number for."""

    rule: str
    met: bool
    reason: str
    current: str | None
    required: str | None


@dataclass(frozen=True, slots=True)
class LessonBlockProgressRow:
    """One block as the learner view renders it (0041) — enough to pick
    the right player/viewer component and fetch its content, not the
    full authoring shape (no completion_rules; a learner never sees a
    block's own rule override, only the lesson-level merged verdict in
    `checks`/`unmet_requirements` below)."""

    block_id: uuid.UUID
    position: int
    block_type: str
    body: str | None
    video_asset_id: uuid.UUID | None
    audio_asset_id: uuid.UUID | None
    quiz_id: uuid.UUID | None
    survey_id: uuid.UUID | None
    assignment_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class LessonProgressRow:
    lesson_id: uuid.UUID
    module_id: uuid.UUID
    module_title: str
    module_position: int
    title: str
    position: int
    estimated_minutes: int
    blocks: list[LessonBlockProgressRow]
    state: str
    unmet_requirements: list[str]
    checks: list[LessonCheckRow]


@dataclass(frozen=True, slots=True)
class EnrolmentProgress:
    """What `GET /enrolments/{id}/progress` answers with — the per-lesson
    rows plus the course-level roll-up the learner shell's header needs,
    computed here so no caller re-derives "how far am I" differently."""

    enrolment: Enrolment
    course: Course
    lessons: list[LessonProgressRow]
    progress_percent: int
    next_lesson_id: uuid.UUID | None
    estimated_minutes: int


@dataclass(frozen=True, slots=True)
class VideoContext:
    """The three numbers a video player needs alongside a heartbeat ack:
    how far the server thinks this learner has watched, how far the
    merged completion rules require, and how long the asset runs. All
    null when the lesson has no video or no rule."""

    watched_percentage: int | None
    required_percentage: int | None
    duration_seconds: int | None


@dataclass(frozen=True, slots=True)
class TranscriptLessonRow:
    module_title: str
    title: str
    position: int
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class Transcript:
    learner_name: str
    course_title: str
    enrolled_at: datetime
    completed_at: datetime | None
    certificate_number: str | None
    lessons: list[TranscriptLessonRow]


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


async def _has_access_to_media(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    column: InstrumentedAttribute[uuid.UUID | None],
    asset_id: uuid.UUID,
) -> bool:
    """03 §6.7's entitlement check, run before a playback URL is ever
    minted — a video or audio asset is reachable only through a lesson,
    whose course the caller must hold a real, still-valid entitlement for
    (never just an Enrolment row's existence — a lapsed subscription must
    actually cut off access, services/entitlements.py::
    has_valid_course_entitlement), unless the lesson itself is a free
    preview (`access_level="public"`). `column` (a `LessonBlock` column,
    0041) is walked to every lesson block that references it (there is
    no uniqueness constraint stopping more than one), not just the first
    — any one of them being public, or any one of their courses being
    validly accessible, is enough."""
    rows = (
        await session.execute(
            select(Course.id, Lesson.access_level)
            .join(Module, Module.course_id == Course.id)
            .join(Lesson, Lesson.module_id == Module.id)
            .join(LessonBlock, LessonBlock.lesson_id == Lesson.id)
            .where(column == asset_id)
        )
    ).all()
    if not rows:
        return False
    if any(access_level == "public" for _course_id, access_level in rows):
        return True

    course_ids = [course_id for course_id, _access_level in rows]
    enrolled_stmt = select(Enrolment.course_id).where(
        Enrolment.tenant_id == tenant_id,
        Enrolment.user_id == user_id,
        Enrolment.course_id.in_(course_ids),
    )
    enrolled_course_ids = (await session.execute(enrolled_stmt)).scalars().all()
    for course_id in enrolled_course_ids:
        if await entitlements.has_valid_course_entitlement(
            session, tenant_id=tenant_id, user_id=user_id, course_id=course_id
        ):
            return True
    return False


async def has_access_to_video(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, video_asset_id: uuid.UUID
) -> bool:
    return await _has_access_to_media(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        column=LessonBlock.video_asset_id,
        asset_id=video_asset_id,
    )


async def has_access_to_audio(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, audio_asset_id: uuid.UUID
) -> bool:
    return await _has_access_to_media(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        column=LessonBlock.audio_asset_id,
        asset_id=audio_asset_id,
    )


async def _course_for_lesson_fk(
    session: AsyncSession, column: InstrumentedAttribute[uuid.UUID | None], value: uuid.UUID
) -> Course:
    """Shared by the quiz/survey/assignment enrolment resolvers below —
    each activity is reachable only through the one lesson block that
    references it, same as `has_access_to_video`'s video_asset_id walk.
    `column` is a `LessonBlock` column (0041)."""
    stmt = (
        select(Course)
        .join(Module, Module.course_id == Course.id)
        .join(Lesson, Lesson.module_id == Module.id)
        .join(LessonBlock, LessonBlock.lesson_id == Lesson.id)
        .where(column == value)
    )
    course = (await session.execute(stmt)).scalars().first()
    if course is None:
        raise NotFound("No lesson references this activity.")
    return course


async def _has_view_access_via_lesson_fk(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    column: InstrumentedAttribute[uuid.UUID | None],
    value: uuid.UUID,
) -> bool:
    """View-only access for a quiz/survey/assignment reached through a
    single referencing lesson block — public if the lesson is a free
    preview, otherwise the same real-enrolment-plus-valid-entitlement
    check `has_access_to_video` uses. Never creates an Enrolment or
    touches completion.py — preview is view-only (module docstring).
    `column` is a `LessonBlock` column (0041)."""
    row = (
        await session.execute(
            select(Course.id, Lesson.access_level)
            .join(Module, Module.course_id == Course.id)
            .join(Lesson, Lesson.module_id == Module.id)
            .join(LessonBlock, LessonBlock.lesson_id == Lesson.id)
            .where(column == value)
        )
    ).first()
    if row is None:
        return False
    course_id, access_level = row
    if access_level == "public":
        return True

    enrolment_stmt = select(Enrolment.id).where(
        Enrolment.tenant_id == tenant_id,
        Enrolment.user_id == user_id,
        Enrolment.course_id == course_id,
    )
    if (await session.execute(enrolment_stmt)).first() is None:
        return False
    return await entitlements.has_valid_course_entitlement(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course_id
    )


async def has_view_access_to_quiz(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, quiz_id: uuid.UUID
) -> bool:
    return await _has_view_access_via_lesson_fk(
        session, tenant_id=tenant_id, user_id=user_id, column=LessonBlock.quiz_id, value=quiz_id
    )


async def has_view_access_to_survey(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, survey_id: uuid.UUID
) -> bool:
    return await _has_view_access_via_lesson_fk(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        column=LessonBlock.survey_id,
        value=survey_id,
    )


async def has_view_access_to_assignment(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> bool:
    return await _has_view_access_via_lesson_fk(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        column=LessonBlock.assignment_id,
        value=assignment_id,
    )


async def resolve_enrolment_for_quiz(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, quiz_id: uuid.UUID
) -> Enrolment:
    course = await _course_for_lesson_fk(session, LessonBlock.quiz_id, quiz_id)
    return await get_own_enrolment(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
    )


async def resolve_enrolment_for_survey(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, survey_id: uuid.UUID
) -> Enrolment:
    course = await _course_for_lesson_fk(session, LessonBlock.survey_id, survey_id)
    return await get_own_enrolment(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
    )


async def resolve_enrolment_for_assignment(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> Enrolment:
    course = await _course_for_lesson_fk(session, LessonBlock.assignment_id, assignment_id)
    return await get_own_enrolment(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
    )


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
    # A live check, not just the Enrolment row's existence — a lapsed
    # subscription's entitlement expiring must actually cut off access to
    # new content (services/entitlements.py::has_valid_course_entitlement),
    # not just decorate a column nobody reads. A one-time purchase's
    # entitlement never sets expires_at, so it always passes here — this
    # never restricts a course bought outright, matching
    # services/organisations.py::revoke_seat's deliberate choice not to
    # retroactively cut off access either (revoked_at is untouched by this
    # check on purpose, same reasoning).
    if not await entitlements.has_valid_course_entitlement(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course_id
    ):
        raise Forbidden("Your access to this course has expired.")
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


async def _completed_lesson_ids(
    session: AsyncSession, *, enrolment_id: uuid.UUID, lesson_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if not lesson_ids:
        return set()
    stmt = select(LessonCompletion.lesson_id).where(
        LessonCompletion.enrolment_id == enrolment_id,
        LessonCompletion.lesson_id.in_(lesson_ids),
        LessonCompletion.state == "completed",
    )
    return set((await session.execute(stmt)).scalars().all())


async def _all_prior_lessons_completed(
    session: AsyncSession, *, course_id: uuid.UUID, lesson_id: uuid.UUID, enrolment_id: uuid.UUID
) -> bool:
    """C-2 — the strict-linear chain this module's own docstring already
    claims (02 §13's cohort/drip-release modes aren't built yet), enforced
    server-side rather than merely computed for display
    (`get_progress`'s `previous_completed`). A lesson with no prior
    lessons (the first one) always passes."""
    ordered = await _ordered_lessons(session, course_id)
    ids = [item.lesson.id for item in ordered]
    idx = ids.index(lesson_id)
    prior_ids = ids[:idx]
    if not prior_ids:
        return True
    completed = await _completed_lesson_ids(
        session, enrolment_id=enrolment_id, lesson_ids=prior_ids
    )
    return len(completed) >= len(prior_ids)


async def _all_lessons_completed(
    session: AsyncSession, *, course_id: uuid.UUID, enrolment_id: uuid.UUID
) -> bool:
    """C-2 — the real "is the course actually done" predicate a course
    completion (and everything downstream of `Enrolment.completed_at`,
    including `services/learning_paths.py::all_member_courses_completed`)
    must be gated on, instead of "the positionally-last lesson has a
    completion row" (`next_lesson is None`) — sound only under the
    strict-linear chain `_all_prior_lessons_completed` now enforces at
    every `start_lesson` call, so this is a second, independent check on
    the one moment a certificate gets issued, not a trust of that
    invariant holding by construction alone."""
    ordered = await _ordered_lessons(session, course_id)
    ids = [item.lesson.id for item in ordered]
    if not ids:
        return False
    completed = await _completed_lesson_ids(session, enrolment_id=enrolment_id, lesson_ids=ids)
    return len(completed) >= len(ids)


async def _blocks_of_type(
    session: AsyncSession, *, lesson_id: uuid.UUID, block_type: str
) -> list[LessonBlock]:
    return [
        block
        for block in await lesson_blocks_service.list_blocks(session, lesson_id=lesson_id)
        if block.block_type == block_type
    ]


async def _video_watch_percentage(
    session: AsyncSession, *, lesson_id: uuid.UUID, enrolment_id: uuid.UUID
) -> float | None:
    """The minimum watched percentage across every video block in the
    lesson (0041 — a lesson can hold more than one). `evaluate()`'s
    single threshold check (watched >= required) is true for every block
    iff it's true for the worst one, so this lets the rule engine itself
    stay a single scalar comparison while still ANDing the rule across N
    blocks. None only when there is nothing to check — no video block,
    or none with a usable asset/duration."""
    percentages: list[float] = []
    for block in await _blocks_of_type(session, lesson_id=lesson_id, block_type="video"):
        if block.video_asset_id is None:
            continue
        video_asset = await session.get(VideoAsset, block.video_asset_id)
        if video_asset is None or video_asset.duration_seconds is None:
            continue
        pct = await video_progress_service.watch_percentage(
            session,
            enrolment_id=enrolment_id,
            lesson_block_id=block.id,
            duration_seconds=video_asset.duration_seconds,
        )
        percentages.append(pct or 0.0)
    return min(percentages) if percentages else None


async def _latest_quiz_attempt_for(
    session: AsyncSession, *, quiz_id: uuid.UUID, enrolment_id: uuid.UUID
) -> QuizAttempt | None:
    stmt = (
        select(QuizAttempt)
        .where(
            QuizAttempt.enrolment_id == enrolment_id,
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.invalidated_at.is_(None),
            QuizAttempt.submitted_at.isnot(None),
        )
        .order_by(QuizAttempt.attempt_number.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def _quiz_passed(
    session: AsyncSession, *, lesson_id: uuid.UUID, enrolment_id: uuid.UUID
) -> tuple[bool | None, Decimal | None]:
    """True only if every quiz block in the lesson has a passed attempt;
    None otherwise — never a hard False, matching the single-quiz
    behaviour this generalises (an ungraded or unattempted quiz reads as
    "awaiting", not "failed"). The reported score is the minimum across
    blocks, same reasoning as the video watch-percentage aggregate."""
    blocks = await _blocks_of_type(session, lesson_id=lesson_id, block_type="quiz")
    if not blocks:
        return None, None
    all_passed = True
    scores: list[Decimal] = []
    for block in blocks:
        if block.quiz_id is None:
            all_passed = False
            continue
        attempt = await _latest_quiz_attempt_for(
            session, quiz_id=block.quiz_id, enrolment_id=enrolment_id
        )
        if attempt is None or attempt.passed is not True:
            all_passed = False
        if attempt is not None and attempt.score is not None:
            scores.append(attempt.score)
    return (True, min(scores) if scores else None) if all_passed else (None, None)


async def _survey_responded(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    lesson_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
) -> bool:
    """True only once every survey block in the lesson has been
    responded to."""
    blocks = await _blocks_of_type(session, lesson_id=lesson_id, block_type="survey")
    if not blocks:
        return False
    for block in blocks:
        if block.survey_id is None:
            return False
        survey = await session.get(Survey, block.survey_id)
        if survey is None:  # pragma: no cover - FK guarantees this
            return False
        if not await survey_service.has_responded(
            session, crypto, survey=survey, user_id=user_id, enrolment_id=enrolment_id
        ):
            return False
    return True


async def _assignment_approved(
    session: AsyncSession, *, lesson_id: uuid.UUID, enrolment_id: uuid.UUID
) -> bool:
    """True only once every assignment block in the lesson is approved
    (or, for one that doesn't require approval, submitted at all)."""
    blocks = await _blocks_of_type(session, lesson_id=lesson_id, block_type="assignment")
    if not blocks:
        return False
    for block in blocks:
        if block.assignment_id is None:
            return False
        assignment = await session.get(Assignment, block.assignment_id)
        if assignment is None:  # pragma: no cover - FK guarantees this
            return False
        stmt = (
            select(AssignmentSubmission)
            .where(
                AssignmentSubmission.enrolment_id == enrolment_id,
                AssignmentSubmission.assignment_id == block.assignment_id,
            )
            .order_by(AssignmentSubmission.version.desc())
        )
        latest = (await session.execute(stmt)).scalars().first()
        if latest is None:
            return False
        approved = latest.approved_at is not None if assignment.approval_required else True
        if not approved:
            return False
    return True


@dataclass(frozen=True, slots=True)
class _CompletionContext:
    video_watched_percentage: float | None
    quiz_passed: bool | None
    quiz_score: Decimal | None
    survey_responded: bool
    assignment_approved: bool


async def _completion_context(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    lesson_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
) -> _CompletionContext:
    quiz_passed, quiz_score = await _quiz_passed(
        session, lesson_id=lesson_id, enrolment_id=enrolment_id
    )
    return _CompletionContext(
        video_watched_percentage=await _video_watch_percentage(
            session, lesson_id=lesson_id, enrolment_id=enrolment_id
        ),
        quiz_passed=quiz_passed,
        quiz_score=quiz_score,
        survey_responded=await _survey_responded(
            session, crypto, lesson_id=lesson_id, user_id=user_id, enrolment_id=enrolment_id
        ),
        assignment_approved=await _assignment_approved(
            session, lesson_id=lesson_id, enrolment_id=enrolment_id
        ),
    )


_EMPTY_CONTEXT = _CompletionContext(
    video_watched_percentage=None,
    quiz_passed=None,
    quiz_score=None,
    survey_responded=False,
    assignment_approved=False,
)


def _rules_need_context(rules: CompletionRules) -> bool:
    """`minimum_time_seconds` is answerable from `first_seen_at` alone;
    every other rule needs a round trip to the subsystem that backs it.
    Progress is read far more often than it is written, and most lessons
    carry only a time rule, so the four lookups are skipped unless a rule
    actually asks for them."""
    return (
        rules.video_watch_percentage is not None
        or rules.quiz_pass_score is not None
        or bool(rules.survey_required)
        or bool(rules.assignment_approval_required)
    )


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _check_values(
    rule: str, rules: CompletionRules, ctx: _CompletionContext, *, elapsed_seconds: float
) -> tuple[str | None, str | None]:
    """The two short strings a progress meter renders beside a rule. Null
    for rules with nothing to count (a survey is done or it isn't) —
    never a fabricated "0/1"."""
    if rule == "minimum_time_seconds" and rules.minimum_time_seconds is not None:
        return _clock(elapsed_seconds), _clock(rules.minimum_time_seconds)
    if rule == "video_watch_percentage" and rules.video_watch_percentage is not None:
        return (
            f"{int(ctx.video_watched_percentage or 0)}%",
            f"{rules.video_watch_percentage}%",
        )
    if rule == "quiz_pass_score" and rules.quiz_pass_score is not None:
        current = f"{ctx.quiz_score:.0f}%" if ctx.quiz_score is not None else None
        return current, f"{rules.quiz_pass_score}%"
    return None, None


async def video_context(
    session: AsyncSession,
    *,
    block: LessonBlock,
    lesson: Lesson,
    course: Course,
    enrolment_id: uuid.UUID,
) -> VideoContext:
    """What `POST /lessons/{id}/heartbeat` answers with beside the raw
    counters — the same merged rule set and the same
    `video_progress.watch_percentage` the completion engine reads, so the
    player's progress ring can never disagree with the server's verdict.
    Block-scoped (0041): a lesson can hold more than one video block,
    each tracked independently."""
    duration_seconds: int | None = None
    watched: int | None = None
    if block.video_asset_id is not None:
        asset = await session.get(VideoAsset, block.video_asset_id)
        if asset is not None:
            duration_seconds = asset.duration_seconds
            if duration_seconds:
                percentage = await video_progress_service.watch_percentage(
                    session,
                    enrolment_id=enrolment_id,
                    lesson_block_id=block.id,
                    duration_seconds=duration_seconds,
                )
                watched = int(percentage) if percentage is not None else None
    # Course -> lesson only, two tiers, not three (0041): completion is
    # still evaluated once per lesson, aggregated across that lesson's
    # blocks (see _video_watch_percentage etc.) rather than once per
    # block — so a block's own completion_rules has nothing meaningful
    # to be merged into here yet. It stays on the model for a future
    # per-block evaluation pass, not consulted by v1.
    rules = merge_rules(course.completion_rules, lesson.completion_rules)
    return VideoContext(
        watched_percentage=watched,
        required_percentage=rules.video_watch_percentage,
        duration_seconds=duration_seconds,
    )


async def resolve_enrolment_for_lesson(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, lesson_id: uuid.UUID
) -> tuple[Enrolment, Lesson, Course]:
    """The ownership resolution `start_lesson`/`complete_lesson` each do
    inline, factored out for `POST /lessons/{id}/heartbeat`
    (routers/learning.py) too. The course comes back with it because the
    heartbeat's own response now reports the merged completion rule the
    lesson is being measured against, and that merge needs both."""
    lesson, course = await _get_lesson_and_course(session, lesson_id)
    enrolment = await get_own_enrolment(
        session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
    )
    return enrolment, lesson, course


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

    # C-2: prerequisite locking used to be computed for display only
    # (get_progress's `previous_completed`) and never actually enforced
    # here — a learner could POST straight to the last lesson's /start
    # and, from there, /complete it into a certificate. This is the
    # server-side half of the same strict-linear chain.
    if not await _all_prior_lessons_completed(
        session, course_id=course.id, lesson_id=lesson.id, enrolment_id=enrolment.id
    ):
        raise LessonLocked("Complete the prior lessons in this course before starting this one.")

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


async def persist_certificate_pdf(
    session: AsyncSession,
    storage: StorageService,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    certificate: Certificate,
    raw_verification_token: str,
) -> None:
    """Shared by the course- and path-completion branches below, and by
    `services/learning_paths.py`'s F5 read-repair (docs/research/
    p5-review-findings.md) — same render/upload/stamp sequence
    regardless of which kind of completion triggered it, so exported
    rather than kept private once a second module needed it."""
    verification_url = f"{settings.public_web_url}/verify/{raw_verification_token}"
    pdf_bytes = credentials_service.render_certificate_pdf(
        snapshot=certificate.snapshot,
        certificate_number=certificate.certificate_number,
        verification_url=verification_url,
    )
    pdf_key = f"{tenant_id}/certificates/{certificate.id}.pdf"
    await storage.ensure_container(Container.GENERATED_DOCUMENTS)
    await storage.upload_object(
        Container.GENERATED_DOCUMENTS, pdf_key, pdf_bytes, content_type="application/pdf"
    )
    certificate.pdf_object_key = pdf_key
    await session.flush()


async def complete_lesson(
    session: AsyncSession,
    crypto: CryptoBox,
    storage: StorageService,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
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
    ctx = await _completion_context(
        session, crypto, lesson_id=lesson.id, user_id=user_id, enrolment_id=enrolment.id
    )
    result = evaluate(
        rules,
        first_seen_at=completion.first_seen_at,
        video_watched_percentage=ctx.video_watched_percentage,
        quiz_passed=ctx.quiz_passed,
        survey_responded=ctx.survey_responded,
        assignment_approved=ctx.assignment_approved,
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
    # C-2: "no next lesson by position" used to be trusted as "the course
    # is done" on its own — sound only if every prior lesson was actually
    # completed to reach here, which `start_lesson`'s prerequisite check
    # now guarantees, but `enrolment.completed_at` (and everything that
    # reads it, learning-path certification included) is too consequential
    # to rest on that invariant holding by construction alone. Checked
    # independently here instead.
    course_is_complete = next_lesson is None and await _all_lessons_completed(
        session, course_id=course.id, enrolment_id=enrolment.id
    )
    if course_is_complete:
        enrolment.completed_at = datetime.now(UTC)
        await session.flush()
        # REQ-CRED-01: issued only here, at the exact moment the rule
        # engine has confirmed the whole course is done — never from a
        # direct API call (services/credentials.py's own docstring).
        issued = await credentials_service.issue_for_completed_enrolment(
            session,
            crypto,
            tenant_id=tenant_id,
            enrolment=enrolment,
            course_title=course.title,
            certificate_template_id=course.certificate_template_id,
            badge_template_id=course.badge_template_id,
        )
        if issued.certificate is not None and issued.raw_verification_token is not None:
            await persist_certificate_pdf(
                session,
                storage,
                settings,
                tenant_id=tenant_id,
                certificate=issued.certificate,
                raw_verification_token=issued.raw_verification_token,
            )

        # P5: this course completing might also complete a learning path
        # this learner is on. Checked here, not from a separate endpoint —
        # the only trustworthy moment is the instant membership actually
        # confirms it, same REQ-CRED-01 reasoning as the course branch
        # above. Local import: services/learning_paths.py imports this
        # module (for get_path_progress), so a module-level import here
        # would cycle; by the time this function runs, both modules are
        # already fully loaded.
        from src.services import learning_paths as paths_service

        for path_enrolment in await paths_service.find_path_enrolments_for_course_completion(
            session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
        ):
            if not await paths_service.all_member_courses_completed(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                learning_path_id=path_enrolment.learning_path_id,
            ):
                continue
            path_enrolment.completed_at = datetime.now(UTC)
            await session.flush()
            path = await session.get(LearningPath, path_enrolment.learning_path_id)
            if path is None:  # pragma: no cover - FK guarantees this
                continue
            issued_path = await credentials_service.issue_for_completed_path(
                session,
                crypto,
                tenant_id=tenant_id,
                path_enrolment=path_enrolment,
                path_title=path.title,
                certificate_template_id=path.certificate_template_id,
            )
            if (
                issued_path.certificate is not None
                and issued_path.raw_verification_token is not None
            ):
                await persist_certificate_pdf(
                    session,
                    storage,
                    settings,
                    tenant_id=tenant_id,
                    certificate=issued_path.certificate,
                    raw_verification_token=issued_path.raw_verification_token,
                )
    await session.flush()
    return completion, next_lesson


async def get_progress(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
) -> EnrolmentProgress:
    """03 §6.1 — the UI renders its checklist from `checks`/
    `unmet_requirements`; it does not compute either. `checks` carries the
    met rules as well as the unmet ones, so a learner can see what they
    have already cleared, not only what is still blocking them;
    `unmet_requirements` is unchanged and still the refusal-reason list.

    Ordering and the per-lesson time estimate both come from
    `course_wizard.get_outline` — the one place video duration, question
    counts and body word counts are turned into minutes — rather than a
    second, subtly different derivation here."""
    enrolment = await _get_own_enrolment_by_id(
        session, tenant_id=tenant_id, user_id=user_id, enrolment_id=enrolment_id
    )
    course = await session.get(Course, enrolment.course_id)
    if course is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such course.")

    outline = await course_wizard.get_outline(session, course_id=course.id, tenant_id=tenant_id)
    completions_stmt = select(LessonCompletion).where(LessonCompletion.enrolment_id == enrolment.id)
    completions = {c.lesson_id: c for c in (await session.execute(completions_stmt)).scalars()}
    now = datetime.now(UTC)

    rows: list[LessonProgressRow] = []
    previous_completed = True
    for module_outline in outline:
        for item in module_outline.lessons:
            lesson = item.lesson
            completion = completions.get(lesson.id)
            unmet: list[str] = []

            if completion is not None:
                state = completion.state
            elif previous_completed:
                state = "available"
            else:
                state = "locked"
                unmet = ["Complete the previous lesson first."]

            rules = merge_rules(course.completion_rules, lesson.completion_rules)
            ctx = (
                await _completion_context(
                    session, crypto, lesson_id=lesson.id, user_id=user_id, enrolment_id=enrolment.id
                )
                if _rules_need_context(rules)
                else _EMPTY_CONTEXT
            )
            # A lesson with no completion row has never been opened, so
            # there is no server-assigned start to measure elapsed time
            # against — `now` makes that read as 0s spent, which is the
            # truth, rather than silently dropping the rule.
            first_seen_at = completion.first_seen_at if completion is not None else now
            result = evaluate(
                rules,
                first_seen_at=first_seen_at,
                now=now,
                video_watched_percentage=ctx.video_watched_percentage,
                quiz_passed=ctx.quiz_passed,
                survey_responded=ctx.survey_responded,
                assignment_approved=ctx.assignment_approved,
            )
            elapsed_seconds = (now - first_seen_at).total_seconds()
            checks: list[LessonCheckRow] = []
            for check in result.checks:
                current, required = _check_values(
                    check.rule, rules, ctx, elapsed_seconds=elapsed_seconds
                )
                checks.append(
                    LessonCheckRow(
                        rule=check.rule,
                        met=check.met,
                        reason=check.reason,
                        current=current,
                        required=required,
                    )
                )
            if completion is not None and state != "completed":
                unmet = [c.reason for c in result.checks if not c.met]

            rows.append(
                LessonProgressRow(
                    lesson_id=lesson.id,
                    module_id=module_outline.module.id,
                    module_title=module_outline.module.title,
                    module_position=module_outline.module.position,
                    title=lesson.title,
                    position=lesson.position,
                    estimated_minutes=item.estimated_minutes,
                    blocks=[
                        LessonBlockProgressRow(
                            block_id=b.block.id,
                            position=b.block.position,
                            block_type=b.block.block_type,
                            body=b.block.body,
                            video_asset_id=b.block.video_asset_id,
                            audio_asset_id=b.block.audio_asset_id,
                            quiz_id=b.block.quiz_id,
                            survey_id=b.block.survey_id,
                            assignment_id=b.block.assignment_id,
                        )
                        for b in item.blocks
                    ],
                    state=state,
                    unmet_requirements=unmet,
                    checks=checks,
                )
            )
            previous_completed = state == "completed"

    completed_count = sum(1 for row in rows if row.state == "completed")
    next_lesson_id = next(
        (row.lesson_id for row in rows if row.state in ("available", "in_progress")), None
    )
    return EnrolmentProgress(
        enrolment=enrolment,
        course=course,
        lessons=rows,
        progress_percent=round(100 * completed_count / len(rows)) if rows else 0,
        next_lesson_id=next_lesson_id,
        estimated_minutes=sum(row.estimated_minutes for row in rows),
    )


async def get_transcript(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
) -> Transcript:
    """REQ-LMS-06 — completed lessons only, each with the real
    `completed_at` the rule engine assigned, not a re-derived guess."""
    enrolment = await _get_own_enrolment_by_id(
        session, tenant_id=tenant_id, user_id=user_id, enrolment_id=enrolment_id
    )
    course = await session.get(Course, enrolment.course_id)
    if course is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such course.")
    user = await session.get(User, user_id)
    learner_name = identity.display_name(user, crypto) if user is not None else "Learner"

    ordered = await _ordered_lessons(session, course.id)
    completions_stmt = select(LessonCompletion).where(LessonCompletion.enrolment_id == enrolment.id)
    completions = {c.lesson_id: c for c in (await session.execute(completions_stmt)).scalars()}

    lessons = [
        TranscriptLessonRow(
            module_title=item.module.title,
            title=item.lesson.title,
            position=item.lesson.position,
            completed_at=completions[item.lesson.id].completed_at,
        )
        for item in ordered
        if item.lesson.id in completions and completions[item.lesson.id].state == "completed"
    ]

    certificate = (
        await session.execute(select(Certificate).where(Certificate.enrolment_id == enrolment.id))
    ).scalar_one_or_none()

    return Transcript(
        learner_name=learner_name,
        course_title=course.title,
        enrolled_at=enrolment.created_at,
        completed_at=enrolment.completed_at,
        certificate_number=certificate.certificate_number if certificate is not None else None,
        lessons=lessons,
    )


__all__ = [
    "EnrolmentProgress",
    "LessonBlockProgressRow",
    "LessonCheckRow",
    "LessonProgressRow",
    "OwnEnrolmentRow",
    "Transcript",
    "TranscriptLessonRow",
    "VideoContext",
    "complete_lesson",
    "get_or_create_enrolment",
    "get_own_enrolment",
    "get_progress",
    "get_transcript",
    "has_access_to_audio",
    "has_access_to_video",
    "list_own_enrolments",
    "persist_certificate_pdf",
    "resolve_enrolment_for_assignment",
    "resolve_enrolment_for_lesson",
    "resolve_enrolment_for_quiz",
    "resolve_enrolment_for_survey",
    "start_lesson",
    "video_context",
]
