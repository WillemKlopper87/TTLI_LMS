"""Quizzes, surveys, assignments (02 §7.5/7.6/7.7, 03 §6.5/6.6,
REQ-ASSESS-01…06, REQ-BYPASS-05/06/07/08).

Authoring endpoints (create quiz/survey/assignment, add a question,
attach to a lesson) are `course:edit`-gated — narrow additive primitives,
not general CRUD, same stance sprint 2 took for `POST /lessons/{id}/video`.
Learner-facing endpoints resolve the caller's own enrolment via the
lesson the activity is attached to (services/enrolment.py's
`resolve_enrolment_for_{quiz,survey,assignment}`), the same ownership
pattern already used throughout routers/learning.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy import select

from src.core.deps import CryptoDep, PrincipalDep, SessionDep, SettingsDep, StorageDep
from src.core.errors import AppError, NotFound, ServiceUnavailable
from src.core.ids import uuid7
from src.models.assessment import (
    Assignment,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    Survey,
    SurveyQuestion,
)
from src.models.course import Lesson
from src.schemas.assessment import (
    AssignmentCreateRequest,
    AssignmentResponse,
    AssignmentReviewRequest,
    AssignmentSubmissionResponse,
    QuizAttemptResponse,
    QuizAttemptResult,
    QuizCreateRequest,
    QuizGradeRequest,
    QuizQuestionCreateRequest,
    QuizQuestionView,
    QuizResponse,
    QuizSubmitRequest,
    SurveyCreateRequest,
    SurveyQuestionCreateRequest,
    SurveyQuestionView,
    SurveyResponse_,
    SurveyResponseSubmitRequest,
    SurveyView,
)
from src.services import antivirus
from src.services import assignment as assignment_service
from src.services import enrolment as enrolment_service
from src.services import quiz as quiz_service
from src.services import survey as survey_service
from src.services.quiz import AnswerSubmission, question_view
from src.services.storage import Container

router = APIRouter(tags=["assessment"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


# ============================================================ Quizzes ===


@router.post("/quizzes", response_model=QuizResponse, status_code=status.HTTP_201_CREATED)
async def create_quiz(
    body: QuizCreateRequest, principal: PrincipalDep, session: SessionDep
) -> QuizResponse:
    principal.require("course:edit")
    quiz = Quiz(
        id=uuid7(),
        title=body.title,
        randomise_questions=body.randomise_questions,
        randomise_options=body.randomise_options,
        pass_score=body.pass_score,
        max_attempts=body.max_attempts,
        time_limit_seconds=body.time_limit_seconds,
    )
    session.add(quiz)
    await session.flush()
    return QuizResponse(id=str(quiz.id), title=quiz.title)


@router.post(
    "/quizzes/{quiz_id}/questions", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def add_quiz_question(
    quiz_id: str, body: QuizQuestionCreateRequest, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("course:edit")
    if body.question_type not in quiz_service.ALL_QUESTION_TYPES:
        raise AppError(f"Unknown question_type {body.question_type!r}.")
    quiz = await session.get(Quiz, _parse_uuid(quiz_id))
    if quiz is None:
        raise NotFound("No such quiz.")
    session.add(
        QuizQuestion(
            id=uuid7(),
            quiz_id=quiz.id,
            question_type=body.question_type,
            prompt=body.prompt,
            options=[o.model_dump() for o in body.options],
            position=body.position,
            points=body.points,
        )
    )
    await session.flush()


@router.post(
    "/lessons/{lesson_id}/quiz", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def attach_quiz_to_lesson(
    lesson_id: str, quiz_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("course:edit")
    lesson = await session.get(Lesson, _parse_uuid(lesson_id))
    if lesson is None:
        raise NotFound("No such lesson.")
    quiz = await session.get(Quiz, _parse_uuid(quiz_id))
    if quiz is None:
        raise NotFound("No such quiz.")
    lesson.quiz_id = quiz.id
    lesson.activity_type = "quiz"
    await session.flush()


@router.post("/quizzes/{quiz_id}/attempts", response_model=QuizAttemptResponse)
async def start_quiz_attempt(
    quiz_id: str, principal: PrincipalDep, session: SessionDep
) -> QuizAttemptResponse:
    quiz_uuid = _parse_uuid(quiz_id)
    enrolment = await enrolment_service.resolve_enrolment_for_quiz(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id, quiz_id=quiz_uuid
    )
    quiz = await session.get(Quiz, quiz_uuid)
    if quiz is None:  # pragma: no cover - resolve_enrolment_for_quiz already proved it exists
        raise NotFound("No such quiz.")

    attempt = await quiz_service.start_attempt(
        session, tenant_id=principal.tenant_id, enrolment_id=enrolment.id, quiz_id=quiz_uuid
    )

    questions_stmt = select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_uuid)
    by_id = {str(q.id): q for q in (await session.execute(questions_stmt)).scalars()}
    ordered = [by_id[qid] for qid in attempt.question_order if qid in by_id]

    return QuizAttemptResponse(
        attempt_id=str(attempt.id),
        quiz_id=quiz_id,
        attempt_number=attempt.attempt_number,
        time_limit_seconds=quiz.time_limit_seconds,
        questions=[
            QuizQuestionView.model_validate(
                question_view(q, randomise_options=quiz.randomise_options)
            )
            for q in ordered
        ],
    )


@router.post("/quiz-attempts/{attempt_id}/submit", response_model=QuizAttemptResult)
async def submit_quiz_attempt(
    attempt_id: str, body: QuizSubmitRequest, principal: PrincipalDep, session: SessionDep
) -> QuizAttemptResult:
    attempt_uuid = _parse_uuid(attempt_id)
    existing = await session.get(QuizAttempt, attempt_uuid)
    if existing is None:
        raise NotFound("No such attempt.")
    # Independently derived from the caller's own identity, not read back
    # off `existing` — enrolment_id must come from *this* principal so
    # quiz_service.submit_attempt's ownership check (existing.enrolment_id
    # == enrolment.id) is a real check, not a tautology against whatever
    # the attempt row itself already says.
    enrolment = await enrolment_service.resolve_enrolment_for_quiz(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id, quiz_id=existing.quiz_id
    )
    attempt = await quiz_service.submit_attempt(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        enrolment_id=enrolment.id,
        attempt_id=attempt_uuid,
        answers=[
            AnswerSubmission(
                question_id=_parse_uuid(a.question_id),
                selected_option_ids=a.selected_option_ids,
                text_answer=a.text_answer,
            )
            for a in body.answers
        ],
    )
    return QuizAttemptResult(
        attempt_id=str(attempt.id),
        submitted_at=attempt.submitted_at,
        score=attempt.score,
        passed=attempt.passed,
    )


@router.post(
    "/quiz-answers/{answer_id}/grade", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def grade_quiz_answer(
    answer_id: str, body: QuizGradeRequest, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("quiz:grade")
    await quiz_service.grade_text_answer(
        session,
        tenant_id=principal.tenant_id,
        answer_id=_parse_uuid(answer_id),
        points_awarded=body.points_awarded,
    )


# ============================================================ Surveys ===


@router.post("/surveys", response_model=SurveyResponse_, status_code=status.HTTP_201_CREATED)
async def create_survey(
    body: SurveyCreateRequest, principal: PrincipalDep, session: SessionDep
) -> SurveyResponse_:
    principal.require("course:edit")
    survey = Survey(
        id=uuid7(),
        title=body.title,
        response_mode=body.response_mode,
        minimum_group_size=body.minimum_group_size,
    )
    session.add(survey)
    await session.flush()
    return SurveyResponse_(
        id=str(survey.id), title=survey.title, response_mode=survey.response_mode
    )


@router.post(
    "/surveys/{survey_id}/questions", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def add_survey_question(
    survey_id: str, body: SurveyQuestionCreateRequest, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("course:edit")
    survey = await session.get(Survey, _parse_uuid(survey_id))
    if survey is None:
        raise NotFound("No such survey.")
    session.add(
        SurveyQuestion(
            id=uuid7(),
            survey_id=survey.id,
            question_type=body.question_type,
            prompt=body.prompt,
            options=[o.model_dump() for o in body.options],
            position=body.position,
        )
    )
    await session.flush()


@router.post(
    "/lessons/{lesson_id}/survey", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def attach_survey_to_lesson(
    lesson_id: str, survey_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("course:edit")
    lesson = await session.get(Lesson, _parse_uuid(lesson_id))
    if lesson is None:
        raise NotFound("No such lesson.")
    survey = await session.get(Survey, _parse_uuid(survey_id))
    if survey is None:
        raise NotFound("No such survey.")
    lesson.survey_id = survey.id
    lesson.activity_type = "survey"
    await session.flush()


@router.get("/surveys/{survey_id}", response_model=SurveyView)
async def get_survey(survey_id: str, principal: PrincipalDep, session: SessionDep) -> SurveyView:
    survey_uuid = _parse_uuid(survey_id)
    # Fetching the form doesn't submit anything, so this only needs to
    # confirm the caller is enrolled in the course it belongs to — it
    # never touches the anonymity mechanism the actual submission uses.
    await enrolment_service.resolve_enrolment_for_survey(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id, survey_id=survey_uuid
    )
    survey = await session.get(Survey, survey_uuid)
    if survey is None:  # pragma: no cover
        raise NotFound("No such survey.")
    questions_stmt = (
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_uuid)
        .order_by(SurveyQuestion.position)
    )
    questions = (await session.execute(questions_stmt)).scalars()
    return SurveyView(
        survey_id=str(survey.id),
        title=survey.title,
        response_mode=survey.response_mode,
        questions=[
            SurveyQuestionView(
                question_id=str(q.id),
                question_type=q.question_type,
                prompt=q.prompt,
                options=[{"id": o["id"], "text": o["text"]} for o in q.options],
            )
            for q in questions
        ],
    )


@router.post(
    "/surveys/{survey_id}/responses", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def submit_survey_response(
    survey_id: str,
    body: SurveyResponseSubmitRequest,
    request_principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> None:
    survey_uuid = _parse_uuid(survey_id)
    enrolment = await enrolment_service.resolve_enrolment_for_survey(
        session,
        tenant_id=request_principal.tenant_id,
        user_id=request_principal.user_id,
        survey_id=survey_uuid,
    )
    await survey_service.submit_response(
        session,
        crypto,
        tenant_id=request_principal.tenant_id,
        survey_id=survey_uuid,
        user_id=request_principal.user_id,
        enrolment_id=enrolment.id,
        answers=[a.model_dump() for a in body.answers],
        ip=None,
    )


# ========================================================= Assignments ===


@router.post("/assignments", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    body: AssignmentCreateRequest, principal: PrincipalDep, session: SessionDep
) -> AssignmentResponse:
    principal.require("course:edit")
    assignment = Assignment(
        id=uuid7(),
        title=body.title,
        instructions=body.instructions,
        max_score=body.max_score,
        approval_required=body.approval_required,
    )
    session.add(assignment)
    await session.flush()
    return AssignmentResponse(id=str(assignment.id), title=assignment.title)


@router.post(
    "/lessons/{lesson_id}/assignment", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def attach_assignment_to_lesson(
    lesson_id: str, assignment_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("course:edit")
    lesson = await session.get(Lesson, _parse_uuid(lesson_id))
    if lesson is None:
        raise NotFound("No such lesson.")
    assignment = await session.get(Assignment, _parse_uuid(assignment_id))
    if assignment is None:
        raise NotFound("No such assignment.")
    lesson.assignment_id = assignment.id
    lesson.activity_type = "assignment"
    await session.flush()


@router.post(
    "/assignments/{assignment_id}/submissions",
    response_model=AssignmentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_assignment(
    assignment_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> AssignmentSubmissionResponse:
    assignment_uuid = _parse_uuid(assignment_id)
    enrolment = await enrolment_service.resolve_enrolment_for_assignment(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        assignment_id=assignment_uuid,
    )
    data = await file.read()

    # Same fail-closed rule as every other upload in this app
    # (REQ-BYPASS-08) — scanned before storage ever sees the bytes.
    try:
        result = await antivirus.scan(data, settings=settings)
    except antivirus.ScanUnavailable as exc:
        raise ServiceUnavailable("The virus scanner is unavailable. Try again shortly.") from exc
    if not result.clean:
        raise AppError(
            "That file was rejected by the virus scanner and was not stored.",
            {"signature": result.signature},
        )

    filename = file.filename or "submission"
    key = (
        f"{principal.tenant_id}/assignments/{assignment_uuid}/{enrolment.id}/"
        f"{uuid.uuid4().hex}-{filename}"
    )
    await storage.ensure_container(Container.USER_UPLOADS)
    await storage.upload_object(Container.USER_UPLOADS, key, data, content_type=file.content_type)

    submission = await assignment_service.submit(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        enrolment_id=enrolment.id,
        assignment_id=assignment_uuid,
        object_key=key,
    )
    return AssignmentSubmissionResponse(
        id=str(submission.id),
        version=submission.version,
        submitted_at=submission.submitted_at,
        approved_at=submission.approved_at,
        rejected_reason=submission.rejected_reason,
    )


@router.post(
    "/assignment-submissions/{submission_id}/review", response_model=AssignmentSubmissionResponse
)
async def review_assignment_submission(
    submission_id: str, body: AssignmentReviewRequest, principal: PrincipalDep, session: SessionDep
) -> AssignmentSubmissionResponse:
    # No dedicated assignment:review permission exists yet, and the
    # facilitator role that would naturally hold one is Phase 5 — quiz:grade
    # ("grade open-ended assessment answers") is the closest real analogue
    # for "human review of learner-submitted work" already seeded.
    principal.require("quiz:grade")
    submission = await assignment_service.review(
        session,
        tenant_id=principal.tenant_id,
        submission_id=_parse_uuid(submission_id),
        reviewer_user_id=principal.user_id,
        approve=body.approve,
        rejected_reason=body.rejected_reason,
    )
    return AssignmentSubmissionResponse(
        id=str(submission.id),
        version=submission.version,
        submitted_at=submission.submitted_at,
        approved_at=submission.approved_at,
        rejected_reason=submission.rejected_reason,
    )


__all__ = ["router"]
