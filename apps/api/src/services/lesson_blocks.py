"""Lesson content blocks (0041) — the ordered sequence of mixed-type
content (text/video/audio/quiz/survey/assignment) that replaced the old
one-activity-per-lesson model. CRUD and atomic reorder only; attaching a
video/audio/quiz/survey/assignment resource to a block is each
subsystem's own job (`src/routers/media.py`, `src/routers/assessment.py`),
same split `services/courses.py` already documents for the old FKs.

Kept beside `services/course_wizard.py` rather than merged into it —
`course_wizard` composes over this module (outline/readiness both need to
read blocks) the same way it already composes over `services/courses.py`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import NotFound
from src.core.ids import uuid7
from src.models.course import BLOCK_TYPE_VALUES, Lesson, LessonBlock
from src.models.learning import LessonCompletion
from src.services.completion import CompletionRules
from src.services.courses import (
    CourseAuthoringError,
    assert_course_authorable,
    resolve_course_id_for_module,
)


def _validate_block_type(block_type: str) -> str:
    if block_type not in BLOCK_TYPE_VALUES:
        raise CourseAuthoringError(
            f"Unknown block type {block_type!r} — must be one of {', '.join(BLOCK_TYPE_VALUES)}."
        )
    return block_type


def _validate_completion_rules(rules: dict[str, object]) -> dict[str, object]:
    try:
        CompletionRules.model_validate(rules)
    except Exception as exc:
        raise CourseAuthoringError(f"Invalid completion_rules: {exc}") from exc
    return rules


async def list_blocks(session: AsyncSession, *, lesson_id: uuid.UUID) -> list[LessonBlock]:
    stmt = (
        select(LessonBlock).where(LessonBlock.lesson_id == lesson_id).order_by(LessonBlock.position)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_block(
    session: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    tenant_id: uuid.UUID,
    block_type: str,
    completion_rules: dict[str, object] | None = None,
) -> LessonBlock:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFound("No such lesson.")
    course_id = await resolve_course_id_for_module(session, module_id=lesson.module_id)
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    _validate_block_type(block_type)
    rules = _validate_completion_rules(completion_rules or {})
    position = (
        await session.execute(
            select(func.count()).select_from(LessonBlock).where(LessonBlock.lesson_id == lesson_id)
        )
    ).scalar_one()
    block = LessonBlock(
        id=uuid7(),
        lesson_id=lesson_id,
        position=position,
        block_type=block_type,
        completion_rules=rules,
    )
    session.add(block)
    await session.flush()
    return block


async def update_block(
    session: AsyncSession,
    *,
    block_id: uuid.UUID,
    tenant_id: uuid.UUID,
    body: str | None = None,
    completion_rules: dict[str, object] | None = None,
) -> LessonBlock:
    block = await session.get(LessonBlock, block_id)
    if block is None:
        raise NotFound("No such block.")
    lesson = await session.get(Lesson, block.lesson_id)
    if lesson is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such block.")
    course_id = await resolve_course_id_for_module(session, module_id=lesson.module_id)
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    if body is not None:
        block.body = body
    if completion_rules is not None:
        block.completion_rules = _validate_completion_rules(completion_rules)
    await session.flush()
    return block


async def _blocks_with_progress(session: AsyncSession, block: LessonBlock) -> bool:
    """Same guard `course_wizard.delete_lesson` applies at the lesson
    level — a block that a learner has already made progress against
    (started the lesson it belongs to, with this block already carrying
    an attempt/submission/watch record) must not be deleted out from
    under them. Keyed on the *lesson*, not the block, matching the
    existing `lesson_completions` grain — there is no per-block
    completion row (see services/enrolment.py's aggregation design)."""
    return bool(
        (
            await session.execute(
                select(func.count())
                .select_from(LessonCompletion)
                .where(LessonCompletion.lesson_id == block.lesson_id)
            )
        ).scalar_one()
    )


async def _renumber_blocks(session: AsyncSession, lesson_id: uuid.UUID) -> None:
    for index, block in enumerate(await list_blocks(session, lesson_id=lesson_id)):
        block.position = index
    await session.flush()


async def delete_block(session: AsyncSession, *, block_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    block = await session.get(LessonBlock, block_id)
    if block is None:
        raise NotFound("No such block.")
    lesson = await session.get(Lesson, block.lesson_id)
    if lesson is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such block.")
    course_id = await resolve_course_id_for_module(session, module_id=lesson.module_id)
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    if await _blocks_with_progress(session, block):
        raise CourseAuthoringError(
            "This lesson has learner progress recorded against it and its blocks "
            "cannot be deleted. Unpublish the course or leave the block in place."
        )
    lesson_id = block.lesson_id
    await session.delete(block)
    await session.flush()
    await _renumber_blocks(session, lesson_id)


async def reorder_blocks(
    session: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ordered_ids: list[uuid.UUID],
) -> list[LessonBlock]:
    """The whole permutation in one transaction — same reasoning as
    `course_wizard.reorder_lessons`: sequential per-item position PATCHes
    can race and leave duplicate positions, which matters here too since
    a lesson's blocks render in `position` order for the learner.

    Local import: `course_wizard` also imports this module (to build the
    outline/readiness reports over blocks) — a module-level import here
    would cycle; by the time this function runs, both modules are
    already fully loaded, same reasoning as `enrolment.py`'s own
    local import of `learning_paths`.
    """
    from src.services.course_wizard import _check_permutation

    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFound("No such lesson.")
    course_id = await resolve_course_id_for_module(session, module_id=lesson.module_id)
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)

    blocks = await list_blocks(session, lesson_id=lesson_id)
    _check_permutation([b.id for b in blocks], ordered_ids, "block")
    by_id = {b.id: b for b in blocks}
    for index, block_id in enumerate(ordered_ids):
        by_id[block_id].position = index
    await session.flush()
    return await list_blocks(session, lesson_id=lesson_id)


__all__ = [
    "create_block",
    "delete_block",
    "list_blocks",
    "reorder_blocks",
    "update_block",
]
