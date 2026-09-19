"""The I/O half of `services/dashboard.py` — BACKLOG.md F4: for each
enrolment's one currently-available lesson, `get_dashboard` looped over
that lesson's quiz blocks and issued two more queries per block (one
`session.get` for the quiz, one attempts-remaining count) — a lesson
with N quiz blocks cost roughly `2N` extra queries on top of the fixed
per-enrolment reads.

The enrolment/progress/certificate reads that also happen once per
enrolment are not this finding and are deliberately held constant here
(a single enrolment, always) so the comparison isolates the one thing
F4 is about: whether the quiz-block loop's cost scales with the number
of *blocks* in the available lesson, not with the number of enrolments.
`services/enrolment.py::get_progress` only ever marks one lesson per
enrolment "available"/"in_progress" at a time (sequential unlock), so
stacking multiple graded quiz blocks onto that one lesson is what makes
an N+1 observable without needing to complete lessons to advance.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from src.core.db import init_engine
from src.core.ids import uuid7
from src.models.assessment import Quiz
from src.models.commerce import Entitlement
from src.models.course import Course, Lesson, LessonBlock, Module
from src.models.learning import Enrolment
from src.services import dashboard, identity

from tests._query_counting import count_queries

pytestmark = pytest.mark.integration


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _seed_enrolment_with_open_quiz_blocks(
    tenant_session_factory, crypto, *, tenant_id: uuid.UUID, quiz_blocks: int
) -> uuid.UUID:  # type: ignore[no-untyped-def]
    """Returns a user_id enrolled, with no lessons completed, in a fresh
    course whose one lesson holds `quiz_blocks` graded quiz blocks — so
    that lesson is the learner's single "available" one and all of its
    blocks are upcoming assessments."""
    async with tenant_session_factory(tenant_id) as s:
        email = f"dashboard-io-{uuid.uuid4().hex[:10]}@example.com"
        user = await identity.create_user(s, crypto, tenant_id=tenant_id, email=email)

        course = Course(
            id=uuid7(),
            slug=f"dash-io-{uuid.uuid4().hex[:8]}",
            title="Dashboard IO Test",
            created_by_tenant_id=tenant_id,
            state="published",
        )
        s.add(course)
        await s.flush()
        module = Module(id=uuid7(), course_id=course.id, title="Module 1", position=1)
        s.add(module)
        await s.flush()
        lesson = Lesson(id=uuid7(), module_id=module.id, title="Lesson 1", position=1)
        s.add(lesson)
        await s.flush()

        for i in range(quiz_blocks):
            quiz = Quiz(id=uuid7(), title=f"Quiz {i}", weight=Decimal("1"), max_attempts=3)
            s.add(quiz)
            await s.flush()
            s.add(
                LessonBlock(
                    id=uuid7(),
                    lesson_id=lesson.id,
                    position=i + 1,
                    block_type="quiz",
                    quiz_id=quiz.id,
                )
            )

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

        return user.id


async def test_get_dashboard_query_count_does_not_scale_with_quiz_block_count(
    settings, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """F4: the fix batches the quiz lookups and their attempts-remaining
    counts across all of a lesson's blocks into two queries, so the total
    is a small constant regardless of how many quiz blocks the learner's
    current lesson has — not `2N`. Proven by comparing a 1-block lesson
    against a 6-block one for a single enrolment, so only the block-loop
    cost can explain a difference."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    engine = init_engine(settings)

    small_user_id = await _seed_enrolment_with_open_quiz_blocks(
        tenant_session_factory, crypto, tenant_id=tenant_id, quiz_blocks=1
    )
    large_user_id = await _seed_enrolment_with_open_quiz_blocks(
        tenant_session_factory, crypto, tenant_id=tenant_id, quiz_blocks=6
    )

    async with tenant_session_factory(tenant_id) as s:
        with count_queries(engine) as statements:
            small_dashboard = await dashboard.get_dashboard(
                s, crypto, tenant_id=tenant_id, user_id=small_user_id
            )
        small_count = len(statements)

    async with tenant_session_factory(tenant_id) as s:
        with count_queries(engine) as statements:
            large_dashboard = await dashboard.get_dashboard(
                s, crypto, tenant_id=tenant_id, user_id=large_user_id
            )
        large_count = len(statements)

    # Sanity: both dashboards actually reflect their own fixture sizes,
    # so a trivially-empty query count isn't hiding a broken query.
    assert len(small_dashboard.upcoming) == 1
    assert len(large_dashboard.upcoming) == 6

    assert large_count == small_count, (
        f"query count scaled with quiz block count ({small_count} for 1 block, "
        f"{large_count} for 6) — the N+1 is back"
    )
