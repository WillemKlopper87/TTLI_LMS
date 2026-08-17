"""The course-authoring *wizard* primitives (`docs/research/course-
authoring-wizard.md`): everything the guided create-and-upload flow
needs that `services/courses.py`'s single-item CRUD couldn't express —
delete with a progress guard, atomic reorder, detach-to-document,
clearing a template link, a full course outline in one read, a
readiness report, a course-wide time estimate, and duplicate-as-
template.

Kept beside rather than inside `services/courses.py` on purpose: that
module is the per-item authoring surface every subsystem's attach
endpoint already relies on; this one composes over it and over the
quiz/survey/assignment/video subsystems it deliberately never touched.

Nothing here introduces a staging store. A course is invisible and
unsellable until it is `published` AND tenant-assigned AND wrapped in
an active priced product, so the wizard writes real rows at every step
and `state="draft"` *is* the draft mechanism — autosave for free.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import NotFound
from src.core.ids import uuid7
from src.models.assessment import Assignment, Quiz, QuizQuestion, Survey, SurveyQuestion
from src.models.commerce import Price, Product
from src.models.course import Course, CourseTenantAssignment, Lesson, Module
from src.models.learning import LessonCompletion
from src.models.media import VideoAsset
from src.services.courses import (
    CourseAuthoringError,
    _unique_slug,
    get_course,
    list_lessons,
    list_modules,
)

# --- Delete (with a progress guard) --------------------------------------


async def _lessons_with_progress(session: AsyncSession, lesson_ids: list[uuid.UUID]) -> int:
    if not lesson_ids:
        return 0
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(LessonCompletion)
                .where(LessonCompletion.lesson_id.in_(lesson_ids))
            )
        ).scalar_one()
    )


async def _renumber_modules(session: AsyncSession, course_id: uuid.UUID) -> None:
    for index, module in enumerate(await list_modules(session, course_id=course_id)):
        module.position = index
    await session.flush()


async def _renumber_lessons(session: AsyncSession, module_id: uuid.UUID) -> None:
    for index, lesson in enumerate(await list_lessons(session, module_id=module_id)):
        lesson.position = index
    await session.flush()


async def delete_lesson(session: AsyncSession, *, lesson_id: uuid.UUID) -> None:
    """Refused once any learner has progress against the lesson —
    `lesson_completions` is the audit trail a certificate was issued
    on, and deleting it from under an issued credential would make
    `/verify/{token}` lie. Siblings are renumbered so `position` stays
    a gapless 0..n-1, which `services/enrolment.py`'s prerequisite
    ordering relies on."""
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFound("No such lesson.")
    if await _lessons_with_progress(session, [lesson.id]):
        raise CourseAuthoringError(
            "This lesson has learner progress recorded against it and cannot be deleted. "
            "Unpublish the course or leave the lesson in place."
        )
    module_id = lesson.module_id
    await session.delete(lesson)
    await session.flush()
    await _renumber_lessons(session, module_id)


async def delete_module(session: AsyncSession, *, module_id: uuid.UUID) -> None:
    module = await session.get(Module, module_id)
    if module is None:
        raise NotFound("No such module.")
    lessons = await list_lessons(session, module_id=module_id)
    if await _lessons_with_progress(session, [lesson.id for lesson in lessons]):
        raise CourseAuthoringError(
            "A lesson in this module has learner progress recorded against it; "
            "the module cannot be deleted."
        )
    course_id = module.course_id
    await session.delete(module)  # lessons cascade at the DB level (0009)
    await session.flush()
    await _renumber_modules(session, course_id)


# --- Atomic reorder ------------------------------------------------------


def _check_permutation(expected: list[uuid.UUID], given: list[uuid.UUID], noun: str) -> None:
    if sorted(expected) != sorted(given) or len(given) != len(set(given)):
        raise CourseAuthoringError(
            f"Reorder must list every {noun} exactly once — got {len(given)}, "
            f"expected {len(expected)}."
        )


async def reorder_modules(
    session: AsyncSession, *, course_id: uuid.UUID, ordered_ids: list[uuid.UUID]
) -> list[Module]:
    """The whole permutation in one transaction. Sequential per-item
    position PATCHes race and can leave duplicate positions; that
    matters because prerequisite order is `(module.position,
    lesson.position)` — learner-facing correctness, not cosmetics."""
    modules = await list_modules(session, course_id=course_id)
    _check_permutation([m.id for m in modules], ordered_ids, "module")
    by_id = {m.id: m for m in modules}
    for index, module_id in enumerate(ordered_ids):
        by_id[module_id].position = index
    await session.flush()
    return await list_modules(session, course_id=course_id)


async def reorder_lessons(
    session: AsyncSession, *, module_id: uuid.UUID, ordered_ids: list[uuid.UUID]
) -> list[Lesson]:
    lessons = await list_lessons(session, module_id=module_id)
    if not lessons and await session.get(Module, module_id) is None:
        raise NotFound("No such module.")
    _check_permutation([lesson.id for lesson in lessons], ordered_ids, "lesson")
    by_id = {lesson.id: lesson for lesson in lessons}
    for index, lesson_id in enumerate(ordered_ids):
        by_id[lesson_id].position = index
    await session.flush()
    return await list_lessons(session, module_id=module_id)


# --- Detach / clear ------------------------------------------------------


async def detach_lesson_activity(session: AsyncSession, *, lesson_id: uuid.UUID) -> Lesson:
    """The reverse of the four `POST /lessons/{id}/quiz|survey|
    assignment|video` attach endpoints, which until now were one-way.
    Clears every activity FK (only one is ever set, but clearing all
    four means a lesson can never be left claiming `document` with a
    stale `quiz_id`) and reverts to `document`. The quiz/survey/
    assignment/video asset itself is *not* deleted — it may be attached
    elsewhere, and "attach existing" is a first-class path in the panel."""
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFound("No such lesson.")
    lesson.quiz_id = None
    lesson.survey_id = None
    lesson.assignment_id = None
    lesson.video_asset_id = None
    lesson.activity_type = "document"
    await session.flush()
    return lesson


async def clear_course_templates(
    session: AsyncSession, *, course_id: uuid.UUID, certificate: bool, badge: bool
) -> Course:
    """`update_course` treats `None` as "unchanged" for every field, so
    "no certificate" was unreachable once one had been attached."""
    course = await get_course(session, course_id=course_id)
    if certificate:
        course.certificate_template_id = None
    if badge:
        course.badge_template_id = None
    await session.flush()
    return course


# --- Outline (one read for the whole tree) -------------------------------


@dataclass
class LessonOutline:
    lesson: Lesson
    video_state: str | None = None
    video_duration_seconds: int | None = None
    video_has_captions: bool = False
    question_count: int | None = None
    estimated_minutes: int = 0


@dataclass
class ModuleOutline:
    module: Module
    lessons: list[LessonOutline] = field(default_factory=list)


_WORDS_PER_MINUTE = 200
_MINUTES_PER_QUIZ_QUESTION = 1
_MINUTES_PER_SURVEY_QUESTION = 0.5
_MINUTES_PER_ASSIGNMENT = 30


def _estimate_lesson_minutes(item: LessonOutline) -> int:
    lesson = item.lesson
    if lesson.activity_type == "video" and item.video_duration_seconds:
        return max(1, round(item.video_duration_seconds / 60))
    if lesson.activity_type == "quiz":
        return max(1, (item.question_count or 0) * _MINUTES_PER_QUIZ_QUESTION)
    if lesson.activity_type == "survey":
        return max(1, round((item.question_count or 0) * _MINUTES_PER_SURVEY_QUESTION))
    if lesson.activity_type == "assignment":
        return _MINUTES_PER_ASSIGNMENT
    words = len((lesson.body or "").split())
    return max(1, round(words / _WORDS_PER_MINUTE)) if words else 0


async def get_outline(session: AsyncSession, *, course_id: uuid.UUID) -> list[ModuleOutline]:
    """Modules → lessons plus the per-lesson facts the wizard's tree
    view and the readiness report both need (video state/captions,
    question counts, a time estimate) — one call instead of N+1 from
    the browser."""
    await get_course(session, course_id=course_id)
    modules = await list_modules(session, course_id=course_id)
    outline: list[ModuleOutline] = []
    all_lessons: list[Lesson] = []
    for module in modules:
        lessons = await list_lessons(session, module_id=module.id)
        outline.append(
            ModuleOutline(module=module, lessons=[LessonOutline(lesson=x) for x in lessons])
        )
        all_lessons.extend(lessons)

    video_ids = {x.video_asset_id for x in all_lessons if x.video_asset_id}
    quiz_ids = {x.quiz_id for x in all_lessons if x.quiz_id}
    survey_ids = {x.survey_id for x in all_lessons if x.survey_id}

    videos: dict[uuid.UUID, VideoAsset] = {}
    if video_ids:
        rows = (
            await session.execute(select(VideoAsset).where(VideoAsset.id.in_(video_ids)))
        ).scalars()
        videos = {v.id: v for v in rows}
    quiz_counts: dict[uuid.UUID, int] = {}
    if quiz_ids:
        rows2 = await session.execute(
            select(QuizQuestion.quiz_id, func.count())
            .where(QuizQuestion.quiz_id.in_(quiz_ids))
            .group_by(QuizQuestion.quiz_id)
        )
        quiz_counts = {row[0]: int(row[1]) for row in rows2.all()}
    survey_counts: dict[uuid.UUID, int] = {}
    if survey_ids:
        rows3 = await session.execute(
            select(SurveyQuestion.survey_id, func.count())
            .where(SurveyQuestion.survey_id.in_(survey_ids))
            .group_by(SurveyQuestion.survey_id)
        )
        survey_counts = {row[0]: int(row[1]) for row in rows3.all()}

    for module_outline in outline:
        for item in module_outline.lessons:
            lesson = item.lesson
            if lesson.video_asset_id and lesson.video_asset_id in videos:
                asset = videos[lesson.video_asset_id]
                item.video_state = asset.state
                item.video_duration_seconds = asset.duration_seconds
                item.video_has_captions = asset.caption_object_key is not None
            if lesson.quiz_id:
                item.question_count = quiz_counts.get(lesson.quiz_id, 0)
            if lesson.survey_id:
                item.question_count = survey_counts.get(lesson.survey_id, 0)
            item.estimated_minutes = _estimate_lesson_minutes(item)
    return outline


# --- Readiness -----------------------------------------------------------


@dataclass
class ReadinessCheck:
    code: str
    level: str  # "blocker" | "warning" | "info"
    ok: bool
    message: str


@dataclass
class Readiness:
    checks: list[ReadinessCheck]
    publishable: bool
    score: int
    estimated_minutes: int
    lesson_count: int
    module_count: int


async def get_readiness(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID
) -> Readiness:
    """The same truth `publish_course` enforces, made visible *before*
    the button — plus the content-level checks publish itself never
    looked at. Blockers are what publish would (or should) refuse;
    warnings are things a learner would notice; info is commercial
    wiring that lives outside `course:edit` (tenant assignment,
    pricing) so a content author sees what still needs an admin.
    Publish stays server-enforced elsewhere; this only reports."""
    course = await get_course(session, course_id=course_id)
    outline = await get_outline(session, course_id=course_id)
    checks: list[ReadinessCheck] = []

    def add(code: str, level: str, ok: bool, message: str) -> None:
        checks.append(ReadinessCheck(code=code, level=level, ok=ok, message=message))

    modules = [m.module for m in outline]
    lessons = [item for m in outline for item in m.lessons]

    add(
        "has_modules",
        "blocker",
        bool(modules),
        "At least one module" if modules else "The course has no modules yet.",
    )
    empty = [m.module.title for m in outline if not m.lessons]
    add(
        "modules_have_lessons",
        "blocker",
        not empty,
        "Every module has at least one lesson"
        if not empty
        else f"Module(s) with no lessons: {', '.join(empty)}.",
    )

    not_ready = [
        item.lesson.title
        for item in lessons
        if item.lesson.activity_type == "video" and item.video_state != "ready"
    ]
    add(
        "videos_ready",
        "blocker",
        not not_ready,
        "All video lessons have a playable (transcoded) asset"
        if not not_ready
        else f"Video still uploading/transcoding or failed: {', '.join(not_ready)}.",
    )
    empty_quizzes = [
        item.lesson.title
        for item in lessons
        if item.lesson.activity_type == "quiz" and not item.question_count
    ]
    add(
        "quizzes_have_questions",
        "blocker",
        not empty_quizzes,
        "Every quiz lesson has at least one question"
        if not empty_quizzes
        else f"Quiz lesson(s) with no questions: {', '.join(empty_quizzes)}.",
    )
    empty_surveys = [
        item.lesson.title
        for item in lessons
        if item.lesson.activity_type == "survey" and not item.question_count
    ]
    add(
        "surveys_have_questions",
        "blocker",
        not empty_surveys,
        "Every survey lesson has at least one question"
        if not empty_surveys
        else f"Survey lesson(s) with no questions: {', '.join(empty_surveys)}.",
    )

    # Completion rules that reference a subsystem no lesson provides —
    # services/completion.py fails loudly rather than skipping, so a
    # learner would hit a wall the author never saw.
    rules: dict[str, Any] = dict(course.completion_rules or {})
    types = {item.lesson.activity_type for item in lessons}
    orphaned: list[str] = []
    if rules.get("quiz_pass_score") is not None and "quiz" not in types:
        orphaned.append("quiz_pass_score (no quiz lesson)")
    if rules.get("video_watch_percentage") is not None and "video" not in types:
        orphaned.append("video_watch_percentage (no video lesson)")
    if rules.get("survey_required") and "survey" not in types:
        orphaned.append("survey_required (no survey lesson)")
    if rules.get("assignment_approval_required") and "assignment" not in types:
        orphaned.append("assignment_approval_required (no assignment lesson)")
    add(
        "completion_rules_satisfiable",
        "blocker",
        not orphaned,
        "Completion rules only reference activities the course actually has"
        if not orphaned
        else f"Completion rule(s) no lesson can satisfy: {', '.join(orphaned)}.",
    )

    add(
        "has_description",
        "warning",
        bool((course.description or "").strip()),
        "The course has a description"
        if course.description
        else "No description — the catalogue card will show only a title.",
    )
    uncaptioned = [
        item.lesson.title
        for item in lessons
        if item.lesson.activity_type == "video" and not item.video_has_captions
    ]
    add(
        "videos_captioned",
        "warning",
        not uncaptioned,
        "All videos have captions (WCAG 1.2.2)"
        if not uncaptioned
        else f"Video(s) without captions: {', '.join(uncaptioned)}.",
    )
    add(
        "has_certificate",
        "warning",
        course.certificate_template_id is not None,
        "A certificate template is attached"
        if course.certificate_template_id
        else "No certificate template — learners get no credential on completion.",
    )
    has_public = any(item.lesson.access_level == "public" for item in lessons)
    add(
        "has_free_preview",
        "warning",
        has_public,
        "At least one lesson is a free preview"
        if has_public
        else "No lesson is marked public — free previews feed the guest → lead funnel.",
    )

    add(
        "is_published",
        "info",
        course.state == "published",
        "Published" if course.state == "published" else f"State is {course.state!r}.",
    )
    assigned = (
        await session.execute(
            select(CourseTenantAssignment.id).where(
                CourseTenantAssignment.course_id == course_id,
                CourseTenantAssignment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none() is not None
    add(
        "assigned_to_tenant",
        "info",
        assigned,
        "Assigned to this tenant" if assigned else "Not yet assigned to this tenant.",
    )
    priced = (
        await session.execute(
            select(Product.id)
            .join(Price, Price.product_id == Product.id)
            .where(
                Product.course_id == course_id,
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none() is not None
    add(
        "sellable",
        "info",
        priced,
        "An active, priced product sells this course"
        if priced
        else "Not sellable yet — no active priced product wraps this course.",
    )

    blockers = [c for c in checks if c.level == "blocker"]
    publishable = all(c.ok for c in blockers)
    scored = [c for c in checks if c.level in ("blocker", "warning")]
    score = round(100 * sum(1 for c in scored if c.ok) / len(scored)) if scored else 0
    return Readiness(
        checks=checks,
        publishable=publishable,
        score=score,
        estimated_minutes=sum(item.estimated_minutes for item in lessons),
        lesson_count=len(lessons),
        module_count=len(modules),
    )


# --- Duplicate as template -----------------------------------------------


async def duplicate_course(
    session: AsyncSession, *, course_id: uuid.UUID, title: str | None = None
) -> Course:
    """A `draft` copy: modules and lessons cloned; video assets *shared*
    by FK (assets are global, transcoding is expensive, and the panel's
    "attach existing" path already treats them as reusable); quizzes,
    surveys and assignments *deep-copied* (their lesson attachment is
    1:1 in practice, and an author editing the copy's quiz must not
    silently change the original's). No enrolments, completions,
    tenant assignments or products come along — the copy is unsold and
    unpublished by construction."""
    source = await get_course(session, course_id=course_id)
    new_title = title or f"{source.title} (copy)"
    copy = Course(
        id=uuid7(),
        slug=await _unique_slug(session, new_title),
        title=new_title,
        description=source.description,
        completion_rules=dict(source.completion_rules or {}),
        certificate_template_id=source.certificate_template_id,
        badge_template_id=source.badge_template_id,
        manager_visibility=source.manager_visibility,
    )
    session.add(copy)
    await session.flush()

    for module in await list_modules(session, course_id=course_id):
        new_module = Module(
            id=uuid7(), course_id=copy.id, title=module.title, position=module.position
        )
        session.add(new_module)
        await session.flush()
        for lesson in await list_lessons(session, module_id=module.id):
            new_lesson = Lesson(
                id=uuid7(),
                module_id=new_module.id,
                title=lesson.title,
                position=lesson.position,
                activity_type=lesson.activity_type,
                access_level=lesson.access_level,
                body=lesson.body,
                completion_rules=dict(lesson.completion_rules or {}),
                video_asset_id=lesson.video_asset_id,
            )
            if lesson.quiz_id:
                new_lesson.quiz_id = await _clone_quiz(session, lesson.quiz_id)
            if lesson.survey_id:
                new_lesson.survey_id = await _clone_survey(session, lesson.survey_id)
            if lesson.assignment_id:
                new_lesson.assignment_id = await _clone_assignment(session, lesson.assignment_id)
            session.add(new_lesson)
        await session.flush()
    return copy


async def _clone_quiz(session: AsyncSession, quiz_id: uuid.UUID) -> uuid.UUID:
    quiz = await session.get(Quiz, quiz_id)
    if quiz is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such quiz.")
    new_quiz = Quiz(
        id=uuid7(),
        title=quiz.title,
        randomise_questions=quiz.randomise_questions,
        randomise_options=quiz.randomise_options,
        pass_score=quiz.pass_score,
        max_attempts=quiz.max_attempts,
        time_limit_seconds=quiz.time_limit_seconds,
    )
    session.add(new_quiz)
    await session.flush()
    questions = (
        await session.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.position)
        )
    ).scalars()
    for q in questions:
        session.add(
            QuizQuestion(
                id=uuid7(),
                quiz_id=new_quiz.id,
                question_type=q.question_type,
                prompt=q.prompt,
                options=list(q.options or []),
                position=q.position,
                points=q.points,
            )
        )
    await session.flush()
    return new_quiz.id


async def _clone_survey(session: AsyncSession, survey_id: uuid.UUID) -> uuid.UUID:
    survey = await session.get(Survey, survey_id)
    if survey is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such survey.")
    new_survey = Survey(
        id=uuid7(),
        title=survey.title,
        response_mode=survey.response_mode,
        minimum_group_size=survey.minimum_group_size,
    )
    session.add(new_survey)
    await session.flush()
    questions = (
        await session.execute(
            select(SurveyQuestion)
            .where(SurveyQuestion.survey_id == survey_id)
            .order_by(SurveyQuestion.position)
        )
    ).scalars()
    for q in questions:
        session.add(
            SurveyQuestion(
                id=uuid7(),
                survey_id=new_survey.id,
                question_type=q.question_type,
                prompt=q.prompt,
                options=list(q.options or []),
                position=q.position,
            )
        )
    await session.flush()
    return new_survey.id


async def _clone_assignment(session: AsyncSession, assignment_id: uuid.UUID) -> uuid.UUID:
    assignment = await session.get(Assignment, assignment_id)
    if assignment is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such assignment.")
    new_assignment = Assignment(
        id=uuid7(),
        title=assignment.title,
        instructions=assignment.instructions,
        max_score=assignment.max_score,
        approval_required=assignment.approval_required,
    )
    session.add(new_assignment)
    await session.flush()
    return new_assignment.id


__all__ = [
    "LessonOutline",
    "ModuleOutline",
    "Readiness",
    "ReadinessCheck",
    "clear_course_templates",
    "delete_lesson",
    "delete_module",
    "detach_lesson_activity",
    "duplicate_course",
    "get_outline",
    "get_readiness",
    "reorder_lessons",
    "reorder_modules",
]
