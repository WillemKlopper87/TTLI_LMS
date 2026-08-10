"""Quizzes (02 §7.5, 03 §6.5, REQ-ASSESS-01/02/03, REQ-BYPASS-05/06).

Auto-graded question types (`single_choice`, `multiple_choice`,
`true_false`) score themselves at submission. `short_text`/`long_text`
answers stay ungraded (`points_awarded=None`) until a `quiz:grade` holder
calls `grade_text_answer` — REQ-ASSESS-03's "auto-grading with manual
grading for open-ended responses", built as two real stages rather than
one that pretends open text can score itself. `passed` stays `None`
(not `False`) while any answer is ungraded — genuinely unknown is not
the same as failed, and the completion rule engine (services/completion.py)
treats both `None` and `False` as "not met" without conflating why.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, Forbidden, NotFound
from src.core.ids import uuid7
from src.models.assessment import Quiz, QuizAnswer, QuizAttempt, QuizQuestion
from src.models.audit import AuditAction
from src.services import audit

AUTO_GRADED_TYPES = frozenset({"single_choice", "multiple_choice", "true_false"})
TEXT_TYPES = frozenset({"short_text", "long_text"})
ALL_QUESTION_TYPES = AUTO_GRADED_TYPES | TEXT_TYPES


class AttemptLimitExceeded(AppError):
    status_code = 400
    code = "ATTEMPT_LIMIT_EXCEEDED"


class TimeLimitExceeded(AppError):
    status_code = 400
    code = "TIME_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class AnswerSubmission:
    question_id: uuid.UUID
    selected_option_ids: list[str] | None
    text_answer: str | None


async def _question_bank(session: AsyncSession, quiz_id: uuid.UUID) -> list[QuizQuestion]:
    stmt = (
        select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.position)
    )
    return list((await session.execute(stmt)).scalars())


async def start_attempt(
    session: AsyncSession, *, tenant_id: uuid.UUID, enrolment_id: uuid.UUID, quiz_id: uuid.UUID
) -> QuizAttempt:
    quiz = await session.get(Quiz, quiz_id)
    if quiz is None:
        raise NotFound("No such quiz.")

    count_stmt = (
        select(func.count())
        .select_from(QuizAttempt)
        .where(
            QuizAttempt.enrolment_id == enrolment_id,
            QuizAttempt.quiz_id == quiz_id,
            QuizAttempt.invalidated_at.is_(None),
        )
    )
    existing = (await session.execute(count_stmt)).scalar_one()
    # REQ-BYPASS-06: the attempt limit is enforced here, not trusted from
    # the client — a learner who has exhausted it cannot start another by
    # simply calling this endpoint again.
    if existing >= quiz.max_attempts:
        raise AttemptLimitExceeded(
            f"No attempts remaining ({quiz.max_attempts} allowed).",
            {"max_attempts": quiz.max_attempts},
        )

    questions = await _question_bank(session, quiz_id)
    question_ids = [str(q.id) for q in questions]
    # REQ-BYPASS-05: randomisation decided and persisted server-side at
    # attempt creation — never re-derived from a client-supplied order.
    if quiz.randomise_questions:
        random.shuffle(question_ids)

    attempt = QuizAttempt(
        id=uuid7(),
        tenant_id=tenant_id,
        enrolment_id=enrolment_id,
        quiz_id=quiz_id,
        attempt_number=existing + 1,
        question_order=question_ids,
    )
    session.add(attempt)
    await session.flush()
    return attempt


def question_view(question: QuizQuestion, *, randomise_options: bool) -> dict[str, object]:
    """The learner-facing shape (03 §6.5) — correctness is never included,
    before or after shuffling."""
    options = [{"id": o["id"], "text": o["text"]} for o in question.options]
    if randomise_options and options:
        random.shuffle(options)
    return {
        "question_id": str(question.id),
        "question_type": question.question_type,
        "prompt": question.prompt,
        "options": options,
        "points": question.points,
    }


async def get_own_attempt(
    session: AsyncSession, *, tenant_id: uuid.UUID, enrolment_id: uuid.UUID, attempt_id: uuid.UUID
) -> QuizAttempt:
    attempt = await session.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.tenant_id != tenant_id:
        raise NotFound("No such attempt.")
    if attempt.enrolment_id != enrolment_id:
        raise Forbidden("You do not have access to this attempt.")
    return attempt


async def submit_attempt(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
    attempt_id: uuid.UUID,
    answers: list[AnswerSubmission],
) -> QuizAttempt:
    attempt = await get_own_attempt(
        session, tenant_id=tenant_id, enrolment_id=enrolment_id, attempt_id=attempt_id
    )
    if attempt.submitted_at is not None:
        raise AppError("This attempt was already submitted.")

    quiz = await session.get(Quiz, attempt.quiz_id)
    if quiz is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such quiz.")

    # Time limits enforced against the server-recorded started_at (03
    # §6.5) — never a client-reported elapsed duration.
    if quiz.time_limit_seconds is not None:
        elapsed = (datetime.now(UTC) - attempt.started_at).total_seconds()
        if elapsed > quiz.time_limit_seconds:
            raise TimeLimitExceeded(
                f"The {quiz.time_limit_seconds}s time limit for this attempt has passed."
            )

    questions = {q.id: q for q in await _question_bank(session, quiz.id)}
    submitted_by_question = {a.question_id: a for a in answers}

    total_points = 0
    graded_points = Decimal("0")
    any_ungraded = False

    for question_id, question in questions.items():
        total_points += question.points
        submission = submitted_by_question.get(question_id)

        selected = submission.selected_option_ids if submission else None
        text = submission.text_answer if submission else None

        is_correct: bool | None = None
        points_awarded: Decimal | None = None

        if question.question_type in AUTO_GRADED_TYPES:
            correct_ids = {o["id"] for o in question.options if o.get("correct")}
            chosen_ids = set(selected or [])
            is_correct = chosen_ids == correct_ids
            points_awarded = Decimal(question.points) if is_correct else Decimal("0")
            graded_points += points_awarded
        else:
            any_ungraded = True

        session.add(
            QuizAnswer(
                id=uuid7(),
                tenant_id=tenant_id,
                attempt_id=attempt.id,
                question_id=question_id,
                selected_option_ids=selected,
                text_answer=text,
                is_correct=is_correct,
                points_awarded=points_awarded,
            )
        )

    attempt.submitted_at = datetime.now(UTC)
    attempt.score = (
        (graded_points / total_points * 100) if total_points > 0 else Decimal("0")
    ).quantize(Decimal("0.01"))
    attempt.passed = None if any_ungraded else attempt.score >= quiz.pass_score

    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.QUIZ_ATTEMPT_SUBMITTED,
        actor_user_id=user_id,
        entity_type="quiz_attempt",
        entity_id=attempt.id,
        after={"score": str(attempt.score), "passed": attempt.passed},
    )
    await session.flush()
    return attempt


async def grade_text_answer(
    session: AsyncSession, *, tenant_id: uuid.UUID, answer_id: uuid.UUID, points_awarded: Decimal
) -> QuizAnswer:
    """quiz:grade-gated (REQ-ASSESS-03's manual half). Re-finalises the
    parent attempt's score/passed once every answer has a grade."""
    answer = await session.get(QuizAnswer, answer_id)
    if answer is None or answer.tenant_id != tenant_id:
        raise NotFound("No such answer.")
    question = await session.get(QuizQuestion, answer.question_id)
    if question is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such question.")
    if points_awarded < 0 or points_awarded > question.points:
        raise AppError(f"points_awarded must be between 0 and {question.points}.")

    answer.points_awarded = points_awarded
    answer.is_correct = points_awarded == question.points

    attempt = await session.get(QuizAttempt, answer.attempt_id)
    if attempt is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such attempt.")
    quiz = await session.get(Quiz, attempt.quiz_id)
    if quiz is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such quiz.")

    answers_stmt = select(QuizAnswer).where(QuizAnswer.attempt_id == attempt.id)
    all_answers = list((await session.execute(answers_stmt)).scalars())
    if all(a.points_awarded is not None for a in all_answers):
        questions = {q.id: q for q in await _question_bank(session, quiz.id)}
        total_points = sum(q.points for q in questions.values()) or 1
        total_awarded = sum((a.points_awarded or Decimal("0")) for a in all_answers)
        attempt.score = (Decimal(total_awarded) / total_points * 100).quantize(Decimal("0.01"))
        attempt.passed = attempt.score >= quiz.pass_score

    await session.flush()
    return answer


__all__ = [
    "ALL_QUESTION_TYPES",
    "AUTO_GRADED_TYPES",
    "TEXT_TYPES",
    "AnswerSubmission",
    "AttemptLimitExceeded",
    "TimeLimitExceeded",
    "get_own_attempt",
    "grade_text_answer",
    "question_view",
    "start_attempt",
    "submit_attempt",
]
