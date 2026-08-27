"""Surveys (02 §7.6, 03 §6.6, REQ-ASSESS-05/06).

Anonymous responses never write `user_id` — see 0013's migration
docstring for the blind-index `respondent_reference` design that makes
duplicate rejection *and* completion-gating possible without ever
identifying who responded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.assessment import Survey, SurveyQuestion, SurveyResponse
from src.models.audit import AuditAction
from src.services import audit


def _anonymous_reference(
    crypto: CryptoBox, *, survey_id: uuid.UUID, enrolment_id: uuid.UUID
) -> bytes:
    return crypto.blind_index(f"{survey_id}:{enrolment_id}")


async def has_responded(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    survey: Survey,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
) -> bool:
    """Backs both duplicate-submission rejection and the completion rule
    engine's `survey_required` check — the same lookup either way."""
    if survey.response_mode == "anonymous":
        reference = _anonymous_reference(crypto, survey_id=survey.id, enrolment_id=enrolment_id)
        stmt = select(SurveyResponse.id).where(
            SurveyResponse.survey_id == survey.id,
            SurveyResponse.respondent_reference == reference,
        )
    else:
        stmt = select(SurveyResponse.id).where(
            SurveyResponse.survey_id == survey.id, SurveyResponse.user_id == user_id
        )
    return (await session.execute(stmt)).first() is not None


async def submit_response(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    survey_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
    answers: list[dict[str, Any]],
    ip: str | None,
) -> SurveyResponse:
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise NotFound("No such survey.")

    if await has_responded(
        session, crypto, survey=survey, user_id=user_id, enrolment_id=enrolment_id
    ):
        # REQ-BYPASS-07: duplicate submissions rejected — checked via the
        # same reference an anonymous response would use, so this refusal
        # itself never reveals more than "you already answered."
        raise AppError("A response has already been submitted for this survey.")

    is_anonymous = survey.response_mode == "anonymous"
    response = SurveyResponse(
        id=uuid7(),
        tenant_id=tenant_id,
        survey_id=survey.id,
        user_id=None if is_anonymous else user_id,
        respondent_reference=(
            _anonymous_reference(crypto, survey_id=survey.id, enrolment_id=enrolment_id)
            if is_anonymous
            else None
        ),
        answers=answers,
    )
    session.add(response)
    await session.flush()

    # A matching audit_events row proves anonymisation occurred at
    # submission time (02 §7.6). actor_user_id is None for an anonymous
    # response on purpose — recording the real user_id here would defeat
    # the point of this row being able to prove anonymity was honoured.
    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.SURVEY_RESPONSE_SUBMITTED,
        actor_user_id=None if is_anonymous else user_id,
        entity_type="survey_response",
        entity_id=response.id,
        after={"anonymous": is_anonymous, "survey_id": str(survey_id)},
        ip=ip,
    )
    return response


async def list_surveys(session: AsyncSession) -> list[tuple[Survey, int]]:
    """(survey, question_count) pairs, ordered by title — same global-content
    shape as `courses_service.list_courses`, no tenant filter."""
    stmt = (
        select(Survey, func.count(SurveyQuestion.id))
        .outerjoin(SurveyQuestion, SurveyQuestion.survey_id == Survey.id)
        .group_by(Survey.id)
        .order_by(Survey.title)
    )
    return [(s, count) for s, count in (await session.execute(stmt)).all()]


async def create_survey(
    session: AsyncSession,
    *,
    title: str,
    response_mode: str,
    minimum_group_size: int,
    evaluation_role: str,
    paired_survey_id: uuid.UUID | None,
) -> Survey:
    """Create a standalone/pre survey or the post half of one pre/post pair."""
    if evaluation_role == "standalone":
        if paired_survey_id is not None:
            raise AppError("A standalone survey cannot be paired.")
        pair_id = None
    elif evaluation_role == "pre":
        if paired_survey_id is not None:
            raise AppError("A pre survey starts a new pair; do not supply paired_survey_id.")
        pair_id = uuid7()
    else:
        if paired_survey_id is None:
            raise AppError("A post survey must name its pre survey.")
        pre = await session.get(Survey, paired_survey_id)
        if pre is None or pre.evaluation_role != "pre" or pre.pair_id is None:
            raise AppError("The paired survey must be a pre evaluation.")
        if pre.response_mode != response_mode:
            raise AppError("Pre and post surveys must use the same response mode.")
        existing_post = (
            await session.execute(
                select(Survey.id).where(
                    Survey.pair_id == pre.pair_id, Survey.evaluation_role == "post"
                )
            )
        ).scalar_one_or_none()
        if existing_post is not None:
            raise AppError("That pre survey already has a post evaluation.")
        pair_id = pre.pair_id

    survey = Survey(
        id=uuid7(),
        title=title,
        response_mode=response_mode,
        minimum_group_size=minimum_group_size,
        evaluation_role=evaluation_role,
        pair_id=pair_id,
    )
    session.add(survey)
    await session.flush()
    return survey


@dataclass(frozen=True, slots=True)
class SurveyQuestionAggregate:
    question_id: uuid.UUID
    position: int
    question_type: str
    prompt: str
    options: list[dict[str, Any]]
    counts: dict[str, int] | None
    response_count: int


@dataclass(frozen=True, slots=True)
class SurveyAggregate:
    survey: Survey
    response_count: int
    available: bool
    questions: list[SurveyQuestionAggregate]


@dataclass(frozen=True, slots=True)
class SurveyDeltaOption:
    text: str
    pre_count: int
    post_count: int
    pre_percent: float
    post_percent: float


@dataclass(frozen=True, slots=True)
class SurveyDeltaQuestion:
    position: int
    prompt: str
    pre_response_count: int
    post_response_count: int
    options: list[SurveyDeltaOption]


@dataclass(frozen=True, slots=True)
class SurveyDelta:
    pair_id: uuid.UUID
    pre: SurveyAggregate
    post: SurveyAggregate
    available: bool
    questions: list[SurveyDeltaQuestion]


async def aggregate_results(
    session: AsyncSession, *, tenant_id: uuid.UUID, survey_id: uuid.UUID
) -> SurveyAggregate:
    """REQ-ASSESS-06: minimum_group_size enforced before any aggregate
    result is displayed — `response_count` is always safe to show (it's
    just a number), but `questions` stays empty until enough people have
    answered, whatever the survey's `response_mode`. A free-text question
    (no `options`) reports only how many people answered it, never the
    text itself — reading individual free-text answers is a separate,
    not-yet-built capability, and exposing it here would make "aggregate"
    a lie for exactly the questions REQ-ASSESS-05 cares most about.

    Python-side aggregation, not SQL `GROUP BY`: answers live inline as a
    JSONB array on `SurveyResponse.answers` (0013's design — no separate
    answer table), and response volume for a survey is small enough that
    unnesting JSONB in the query would be more ceremony than it's worth.
    """
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise NotFound("No such survey.")

    responses = (
        (
            await session.execute(
                select(SurveyResponse.answers).where(
                    SurveyResponse.tenant_id == tenant_id,
                    SurveyResponse.survey_id == survey_id,
                )
            )
        )
        .scalars()
        .all()
    )
    response_count = len(responses)
    available = response_count >= survey.minimum_group_size

    questions: list[SurveyQuestionAggregate] = []
    if available:
        question_rows = (
            (
                await session.execute(
                    select(SurveyQuestion)
                    .where(SurveyQuestion.survey_id == survey_id)
                    .order_by(SurveyQuestion.position)
                )
            )
            .scalars()
            .all()
        )
        for q in question_rows:
            counts: dict[str, int] | None = {o["id"]: 0 for o in q.options} if q.options else None
            answered = 0
            for answer_list in responses:
                answer_dicts = cast("list[dict[str, Any]]", answer_list)
                match = next((a for a in answer_dicts if a.get("question_id") == str(q.id)), None)
                if match is None:
                    continue
                answered += 1
                if counts is not None:
                    value = match.get("value")
                    if value in counts:
                        counts[value] += 1
            questions.append(
                SurveyQuestionAggregate(
                    question_id=q.id,
                    position=q.position,
                    question_type=q.question_type,
                    prompt=q.prompt,
                    options=q.options,
                    counts=counts,
                    response_count=answered,
                )
            )

    return SurveyAggregate(
        survey=survey,
        response_count=response_count,
        available=available,
        questions=questions,
    )


async def aggregate_delta(
    session: AsyncSession, *, tenant_id: uuid.UUID, survey_id: uuid.UUID
) -> SurveyDelta:
    survey = await session.get(Survey, survey_id)
    if survey is None:
        raise NotFound("No such survey.")
    if survey.pair_id is None:
        raise AppError("This survey is not part of a pre/post pair.")
    pair = (
        (
            await session.execute(
                select(Survey).where(
                    Survey.pair_id == survey.pair_id,
                    Survey.evaluation_role.in_(("pre", "post")),
                )
            )
        )
        .scalars()
        .all()
    )
    by_role = {item.evaluation_role: item for item in pair}
    if "pre" not in by_role or "post" not in by_role:
        raise AppError("This pre/post pair is not complete yet.")
    pre = await aggregate_results(session, tenant_id=tenant_id, survey_id=by_role["pre"].id)
    post = await aggregate_results(session, tenant_id=tenant_id, survey_id=by_role["post"].id)
    available = pre.available and post.available
    questions: list[SurveyDeltaQuestion] = []
    if available:
        post_by_position = {q.position: q for q in post.questions if q.counts is not None}
        for pre_q in (q for q in pre.questions if q.counts is not None):
            post_q = post_by_position.get(pre_q.position)
            if post_q is None:
                continue
            pre_counts = pre_q.counts
            post_counts = post_q.counts
            if pre_counts is None or post_counts is None:  # narrowed above; keeps mypy honest
                continue
            post_counts_by_text = {
                option["text"].strip().casefold(): post_counts.get(option["id"], 0)
                for option in post_q.options
            }
            options: list[SurveyDeltaOption] = []
            for option in pre_q.options:
                text_value = option["text"]
                pre_count = pre_counts.get(option["id"], 0)
                post_count = post_counts_by_text.get(text_value.strip().casefold(), 0)
                options.append(
                    SurveyDeltaOption(
                        text=text_value,
                        pre_count=pre_count,
                        post_count=post_count,
                        pre_percent=(pre_count / pre_q.response_count * 100)
                        if pre_q.response_count
                        else 0,
                        post_percent=(post_count / post_q.response_count * 100)
                        if post_q.response_count
                        else 0,
                    )
                )
            questions.append(
                SurveyDeltaQuestion(
                    position=pre_q.position,
                    prompt=pre_q.prompt,
                    pre_response_count=pre_q.response_count,
                    post_response_count=post_q.response_count,
                    options=options,
                )
            )
    return SurveyDelta(
        pair_id=survey.pair_id,
        pre=pre,
        post=post,
        available=available,
        questions=questions,
    )


__all__ = [
    "SurveyAggregate",
    "SurveyDelta",
    "SurveyQuestionAggregate",
    "aggregate_delta",
    "aggregate_results",
    "create_survey",
    "has_responded",
    "list_surveys",
    "submit_response",
]
