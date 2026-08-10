"""Surveys (02 §7.6, 03 §6.6, REQ-ASSESS-05/06).

Anonymous responses never write `user_id` — see 0013's migration
docstring for the blind-index `respondent_reference` design that makes
duplicate rejection *and* completion-gating possible without ever
identifying who responded.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.assessment import Survey, SurveyResponse
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


__all__ = ["has_responded", "submit_response"]
