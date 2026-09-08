"""One shared reading of "how is this learner doing" (BACKLOG P18).

Quiz attempts, assignment submissions and lesson completion each grew their
own notion of achievement, and nothing put them on one page: quizzes carry a
`score` and a `passed` flag, assignments were approve/reject with a
`max_score` nothing could mark against (0045 fixed that), and the printable
transcript (REQ-LMS-06) lists completed lessons with no marks at all.

This module is the shared layer over those, and it is deliberately
**additive**. It changes nothing about what completes a lesson or issues a
certificate -- `services/completion.py`'s rule engine remains the only gate
(02 §5.2). A gradebook that quietly became a second completion authority is
how "we added reporting" turns into learners failing courses they had
already passed.

The computation below is pure -- dataclasses in, dataclass out, no session,
no I/O -- so it belongs to the fast test tier (M5) and can be exercised over
the awkward cases directly, rather than only through a seeded database.
`build_for_enrolment` is the thin part that reads rows and hands them here.

The weighting rule, stated once so it is not re-derived per caller:

* Every graded item contributes `weight * (score / max_score)`.
* Ungraded items are **excluded from both** the numerator and the
  denominator, rather than counted as zero. A course half-marked would
  otherwise report every learner as failing, and "not marked yet" is not
  the same claim as "scored nothing". They are reported separately as
  `ungraded`, so a caller can say "62% so far, 3 items outstanding".
* A learner with nothing graded has no percentage at all (`None`), not 0.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import NotFound
from src.models.assessment import Assignment, AssignmentSubmission, Quiz, QuizAttempt
from src.models.course import Lesson, LessonBlock, Module
from src.models.learning import Enrolment

# Two places need to agree on what "out of" means when an item declares a
# nonsensical denominator. A zero or negative max_score cannot produce a
# ratio, so such an item is treated as ungraded rather than crashing a
# learner's whole report.
_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class AchievementItem:
    """One assessable thing, flattened out of whichever table owns it.

    `kind` is the source table's domain name ("quiz", "assignment"), kept
    as a plain string rather than an enum: this is a projection for
    reporting, and a new assessable kind should not require a migration to
    a Postgres enum before it can appear on a report.
    """

    kind: str
    item_id: str
    title: str
    weight: Decimal
    max_score: Decimal
    score: Decimal | None
    passed: bool | None = None

    @property
    def is_graded(self) -> bool:
        """Graded means a mark exists *and* the denominator is usable."""
        return self.score is not None and self.max_score > _ZERO

    @property
    def ratio(self) -> Decimal | None:
        # `is_graded` already proves score is not None; re-testing it here
        # rather than asserting keeps the narrowing without a bare assert
        # (ruff S101 -- asserts vanish under -O).
        if self.score is None or self.max_score <= _ZERO:
            return None
        return self.score / self.max_score


@dataclass(frozen=True, slots=True)
class Gradebook:
    items: tuple[AchievementItem, ...]
    graded: tuple[AchievementItem, ...]
    ungraded: tuple[AchievementItem, ...]
    #: Weighted percentage over graded items only, or None if none are
    #: graded. Rounded to two places for display; callers needing the raw
    #: ratio should recompute from `graded`.
    percentage: Decimal | None
    #: The weight actually represented by `percentage`, so a caller can
    #: say how much of the course the figure covers.
    graded_weight: Decimal
    total_weight: Decimal

    @property
    def is_complete(self) -> bool:
        """Every assessable item has a mark. Note this says nothing about
        whether the learner *completed the course* -- that remains
        services/completion.py's answer, not this module's."""
        return not self.ungraded and bool(self.items)


def build(items: tuple[AchievementItem, ...] | list[AchievementItem]) -> Gradebook:
    """Fold assessable items into one weighted view. Pure."""
    ordered = tuple(items)
    graded = tuple(i for i in ordered if i.is_graded)
    ungraded = tuple(i for i in ordered if not i.is_graded)

    total_weight = sum((i.weight for i in ordered), _ZERO)
    graded_weight = sum((i.weight for i in graded), _ZERO)

    percentage: Decimal | None = None
    if graded_weight > _ZERO:
        earned = sum(
            (i.weight * ratio for i in graded if (ratio := i.ratio) is not None),
            _ZERO,
        )
        percentage = (earned / graded_weight * Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    return Gradebook(
        items=ordered,
        graded=graded,
        ungraded=ungraded,
        percentage=percentage,
        graded_weight=graded_weight,
        total_weight=total_weight,
    )


def validate_score(score: Decimal | None, max_score: int) -> Decimal | None:
    """Guard the one bound a single-table CHECK cannot express.

    `assignment_submissions.score` is constrained non-negative in the
    database, but its ceiling lives on the parent assignment, so it is
    enforced here on the write path. Returns the score unchanged so callers
    can use it inline; raises ValueError on a mark that cannot be honest.
    """
    if score is None:
        return None
    if score < _ZERO:
        raise ValueError("Score cannot be negative.")
    if max_score <= 0:
        raise ValueError("This assignment has no usable maximum score to mark against.")
    if score > Decimal(max_score):
        raise ValueError(f"Score cannot exceed this assignment's maximum of {max_score}.")
    return score


async def build_for_enrolment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
) -> Gradebook:
    """Read one learner's own assessable items and fold them via `build`.

    The thin I/O half. Everything interesting is in `build`; this only
    decides *which* rows represent a learner's standing on each item.

    `user_id` is required, not optional: a learner's marks are exactly as
    private as the transcript beside them (REQ-LMS-06), and scoping on
    `tenant_id` alone would let any authenticated member of a tenant read
    any other learner's results by enrolment id. Staff reporting over other
    people's marks is a separate, permission-gated read that does not exist
    yet -- when it does, it gets its own entry point rather than a nullable
    argument here.

    Two further decisions matter enough to state:

    * The **latest** submitted, non-invalidated quiz attempt counts, not
      the best. That is what `enrolment.py::_latest_quiz_attempt_for`
      already uses to decide whether a lesson's quiz rule is met, and a
      gradebook that scored the best attempt would report a percentage
      disagreeing with the completion engine on the same data.
    * The **highest-version** submission counts for an assignment, which is
      the one the resubmission flow leaves current.
    """
    enrolment = await session.get(Enrolment, enrolment_id)
    if enrolment is None or enrolment.tenant_id != tenant_id or enrolment.user_id != user_id:
        raise NotFound("No such enrolment.")

    blocks = (
        (
            await session.execute(
                select(LessonBlock)
                .join(Lesson, Lesson.id == LessonBlock.lesson_id)
                .join(Module, Module.id == Lesson.module_id)
                .where(
                    Module.course_id == enrolment.course_id,
                    or_(
                        LessonBlock.quiz_id.isnot(None),
                        LessonBlock.assignment_id.isnot(None),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    items: list[AchievementItem] = []

    for block in blocks:
        if block.quiz_id is not None:
            quiz = await session.get(Quiz, block.quiz_id)
            if quiz is None:
                continue
            attempt = (
                (
                    await session.execute(
                        select(QuizAttempt)
                        .where(
                            QuizAttempt.enrolment_id == enrolment_id,
                            QuizAttempt.quiz_id == quiz.id,
                            QuizAttempt.invalidated_at.is_(None),
                            QuizAttempt.submitted_at.isnot(None),
                        )
                        .order_by(QuizAttempt.attempt_number.desc())
                    )
                )
                .scalars()
                .first()
            )
            items.append(
                AchievementItem(
                    kind="quiz",
                    item_id=str(quiz.id),
                    title=quiz.title,
                    weight=quiz.weight,
                    # Quiz scores are already stored as a percentage
                    # (services/quiz.py compares them against pass_score,
                    # itself a percentage), so the denominator is 100.
                    max_score=Decimal(100),
                    score=attempt.score if attempt is not None else None,
                    passed=attempt.passed if attempt is not None else None,
                )
            )
        elif block.assignment_id is not None:
            assignment = await session.get(Assignment, block.assignment_id)
            if assignment is None:
                continue
            submission = (
                (
                    await session.execute(
                        select(AssignmentSubmission)
                        .where(
                            AssignmentSubmission.enrolment_id == enrolment_id,
                            AssignmentSubmission.assignment_id == assignment.id,
                        )
                        .order_by(AssignmentSubmission.version.desc())
                    )
                )
                .scalars()
                .first()
            )
            items.append(
                AchievementItem(
                    kind="assignment",
                    item_id=str(assignment.id),
                    title=assignment.title,
                    weight=assignment.weight,
                    max_score=Decimal(assignment.max_score),
                    score=submission.score if submission is not None else None,
                    # Approval is the assignment's pass/fail signal; a mark
                    # is separate and optional.
                    passed=(submission.approved_at is not None) if submission is not None else None,
                )
            )

    return build(items)


__all__ = [
    "AchievementItem",
    "Gradebook",
    "build",
    "build_for_enrolment",
    "validate_score",
]
