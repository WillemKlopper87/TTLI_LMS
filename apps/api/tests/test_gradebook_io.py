"""The I/O half of `services/gradebook.py` — `build_for_enrolment` reads
rows and hands them to `build()` (fully covered, pure, in
`test_gradebook.py`). This file exists specifically for BACKLOG.md F3:
`build_for_enrolment` looped over every graded block and issued two
more queries per block (one `session.get` for the quiz/assignment, one
for its latest attempt/submission) — a course with N graded blocks cost
roughly `1 + 2N` queries. Fixtures are built directly via the ORM
(bypassing the course-authoring HTTP flow, which this test has no need
to exercise) so the case can use enough blocks to make an N+1 obvious
without a slow multi-endpoint setup per block.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from src.core.db import init_engine
from src.core.ids import uuid7
from src.models.assessment import Assignment, AssignmentSubmission, Quiz, QuizAttempt
from src.models.commerce import Entitlement
from src.models.course import Course, Lesson, LessonBlock, Module
from src.models.learning import Enrolment
from src.services import gradebook, identity

from tests._query_counting import count_queries

pytestmark = pytest.mark.integration


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _seed_course_with_graded_blocks(
    tenant_session_factory,
    crypto,
    *,
    tenant_id: uuid.UUID,
    quiz_blocks: int,
    assignment_blocks: int,
) -> tuple[uuid.UUID, uuid.UUID]:  # type: ignore[no-untyped-def]
    """Returns (user_id, enrolment_id) for a learner enrolled in a fresh
    course with `quiz_blocks` graded, attempted quizzes and
    `assignment_blocks` graded, submitted assignments — each in its own
    lesson, one block per lesson."""
    async with tenant_session_factory(tenant_id) as s:
        email = f"gradebook-io-{uuid.uuid4().hex[:10]}@example.com"
        user = await identity.create_user(s, crypto, tenant_id=tenant_id, email=email)

        course = Course(id=uuid7(), slug=f"gb-io-{uuid.uuid4().hex[:8]}", title="Gradebook IO Test")
        s.add(course)
        await s.flush()
        module = Module(id=uuid7(), course_id=course.id, title="Module 1", position=1)
        s.add(module)
        await s.flush()

        entitlement = Entitlement(
            id=uuid7(), tenant_id=tenant_id, user_id=user.id, kind="course", target_id=course.id
        )
        s.add(entitlement)
        await s.flush()

        enrolment = Enrolment(
            id=uuid7(),
            tenant_id=tenant_id,
            user_id=user.id,
            course_id=course.id,
            entitlement_id=entitlement.id,
        )
        s.add(enrolment)
        await s.flush()

        position = 1
        for i in range(quiz_blocks):
            lesson = Lesson(
                id=uuid7(), module_id=module.id, title=f"Quiz Lesson {i}", position=position
            )
            s.add(lesson)
            await s.flush()
            position += 1
            quiz = Quiz(id=uuid7(), title=f"Quiz {i}", weight=Decimal("1"))
            s.add(quiz)
            await s.flush()
            s.add(
                LessonBlock(
                    id=uuid7(),
                    lesson_id=lesson.id,
                    position=1,
                    block_type="quiz",
                    quiz_id=quiz.id,
                )
            )
            s.add(
                QuizAttempt(
                    id=uuid7(),
                    tenant_id=tenant_id,
                    enrolment_id=enrolment.id,
                    quiz_id=quiz.id,
                    attempt_number=1,
                    submitted_at=datetime.now(UTC),
                    score=Decimal("80"),
                    passed=True,
                )
            )

        for i in range(assignment_blocks):
            lesson = Lesson(
                id=uuid7(), module_id=module.id, title=f"Assignment Lesson {i}", position=position
            )
            s.add(lesson)
            await s.flush()
            position += 1
            assignment = Assignment(id=uuid7(), title=f"Assignment {i}", weight=Decimal("1"))
            s.add(assignment)
            await s.flush()
            s.add(
                LessonBlock(
                    id=uuid7(),
                    lesson_id=lesson.id,
                    position=1,
                    block_type="assignment",
                    assignment_id=assignment.id,
                )
            )
            s.add(
                AssignmentSubmission(
                    id=uuid7(),
                    tenant_id=tenant_id,
                    enrolment_id=enrolment.id,
                    assignment_id=assignment.id,
                    object_key=f"assignment-submissions/{uuid.uuid4().hex}",
                    version=1,
                    score=Decimal("70"),
                )
            )

        return user.id, enrolment.id


async def test_build_for_enrolment_query_count_does_not_scale_with_block_count(
    settings, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """F3: the fix batches the quiz/assignment lookups and their latest-
    attempt/submission lookups into one query each, so the total is a
    small constant regardless of how many graded blocks a course has —
    not `1 + 2N`. Proven by comparing a 2-block course against a
    12-block one and asserting the same query count, not just an
    absolute ceiling that a slower-but-still-N+1 implementation could
    still slip under."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    engine = init_engine(settings)

    small_user_id, small_enrolment_id = await _seed_course_with_graded_blocks(
        tenant_session_factory, crypto, tenant_id=tenant_id, quiz_blocks=1, assignment_blocks=1
    )
    large_user_id, large_enrolment_id = await _seed_course_with_graded_blocks(
        tenant_session_factory, crypto, tenant_id=tenant_id, quiz_blocks=6, assignment_blocks=6
    )

    async with tenant_session_factory(tenant_id) as s:
        with count_queries(engine) as statements:
            small_gradebook = await gradebook.build_for_enrolment(
                s, tenant_id=tenant_id, user_id=small_user_id, enrolment_id=small_enrolment_id
            )
        small_count = len(statements)

    async with tenant_session_factory(tenant_id) as s:
        with count_queries(engine) as statements:
            large_gradebook = await gradebook.build_for_enrolment(
                s, tenant_id=tenant_id, user_id=large_user_id, enrolment_id=large_enrolment_id
            )
        large_count = len(statements)

    # Sanity: both gradebooks actually reflect their own fixture sizes,
    # so a trivially-empty query count isn't hiding a broken query.
    assert len(small_gradebook.items) == 2
    assert len(large_gradebook.items) == 12

    assert large_count == small_count, (
        f"query count scaled with block count ({small_count} for 2 blocks, "
        f"{large_count} for 12) — the N+1 is back"
    )
