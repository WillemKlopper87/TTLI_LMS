"""Tenant-scoped reusable assessment-question templates."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.assessment import QuestionBankItem, Quiz, QuizQuestion, Survey, SurveyQuestion

QUIZ_TYPES = {"single_choice", "multiple_choice", "true_false", "short_text", "long_text"}
SURVEY_TYPES = QUIZ_TYPES


def _normalise_options(
    *, assessment_kind: str, question_type: str, options: list[dict[str, object]]
) -> list[dict[str, object]]:
    choice = question_type in {"single_choice", "multiple_choice", "true_false"}
    if not choice:
        return []
    if len(options) < 2:
        raise AppError("Choice questions require at least two options.")
    if any(not str(option.get("text", "")).strip() for option in options):
        raise AppError("Every option must have text.")
    if assessment_kind == "quiz":
        if not any(option.get("correct") is True for option in options):
            raise AppError("A quiz question requires at least one correct option.")
        return [
            {
                "id": str(option["id"]),
                "text": str(option["text"]),
                "correct": bool(option.get("correct")),
            }
            for option in options
        ]
    return [{"id": str(option["id"]), "text": str(option["text"])} for option in options]


async def list_items(
    session: AsyncSession, *, tenant_id: uuid.UUID, assessment_kind: str | None = None
) -> list[QuestionBankItem]:
    stmt = select(QuestionBankItem).where(QuestionBankItem.tenant_id == tenant_id)
    if assessment_kind is not None:
        stmt = stmt.where(QuestionBankItem.assessment_kind == assessment_kind)
    return list(
        (await session.execute(stmt.order_by(QuestionBankItem.created_at.desc()))).scalars()
    )


async def create_item(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    assessment_kind: str,
    question_type: str,
    prompt: str,
    options: list[dict[str, object]],
    points: int,
) -> QuestionBankItem:
    allowed = QUIZ_TYPES if assessment_kind == "quiz" else SURVEY_TYPES
    if question_type not in allowed:
        raise AppError(f"Unknown question_type {question_type!r}.")
    item = QuestionBankItem(
        id=uuid7(),
        tenant_id=tenant_id,
        assessment_kind=assessment_kind,
        question_type=question_type,
        prompt=prompt,
        options=_normalise_options(
            assessment_kind=assessment_kind, question_type=question_type, options=options
        ),
        points=points if assessment_kind == "quiz" else 1,
    )
    session.add(item)
    await session.flush()
    return item


async def delete_item(session: AsyncSession, *, tenant_id: uuid.UUID, item_id: uuid.UUID) -> None:
    item = await session.get(QuestionBankItem, item_id)
    if item is None or item.tenant_id != tenant_id:
        raise NotFound("No such question-bank item.")
    await session.delete(item)
    await session.flush()


async def apply_to_quiz(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    quiz_id: uuid.UUID,
    position: int,
) -> None:
    item = await session.get(QuestionBankItem, item_id)
    quiz = await session.get(Quiz, quiz_id)
    if item is None or item.tenant_id != tenant_id:
        raise NotFound("No such question-bank item.")
    if quiz is None:
        raise NotFound("No such quiz.")
    if item.assessment_kind != "quiz":
        raise AppError("Only quiz questions can be added to a quiz.")
    session.add(
        QuizQuestion(
            id=uuid7(),
            quiz_id=quiz.id,
            question_type=item.question_type,
            prompt=item.prompt,
            options=item.options,
            position=position,
            points=item.points,
        )
    )
    await session.flush()


async def apply_to_survey(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    survey_id: uuid.UUID,
    position: int,
) -> None:
    item = await session.get(QuestionBankItem, item_id)
    survey = await session.get(Survey, survey_id)
    if item is None or item.tenant_id != tenant_id:
        raise NotFound("No such question-bank item.")
    if survey is None:
        raise NotFound("No such survey.")
    if item.assessment_kind != "survey":
        raise AppError("Only survey questions can be added to a survey.")
    session.add(
        SurveyQuestion(
            id=uuid7(),
            survey_id=survey.id,
            question_type=item.question_type,
            prompt=item.prompt,
            options=item.options,
            position=position,
        )
    )
    await session.flush()


__all__ = ["apply_to_quiz", "apply_to_survey", "create_item", "delete_item", "list_items"]
