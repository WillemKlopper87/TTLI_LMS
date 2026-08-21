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
from src.core.errors import AppError, Forbidden, NotFound, ServiceUnavailable
from src.core.ids import uuid7
from src.core.object_keys import safe_filename
from src.models.assessment import (
    Assignment,
    AssignmentSubmission,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    Survey,
    SurveyQuestion,
)
from src.models.course import Lesson
from src.schemas.assessment import (
    AssignmentCreateRequest,
    AssignmentDetailResponse,
    AssignmentListItem,
    AssignmentResponse,
    AssignmentReviewRequest,
    AssignmentsPageResponse,
    AssignmentSubmissionResponse,
    PendingSubmissionItem,
    PendingSubmissionsResponse,
    QuizAttemptResponse,
    QuizAttemptResult,
    QuizCreateRequest,
    QuizDetailResponse,
    QuizGradeRequest,
    QuizListItem,
    QuizPreviewResponse,
    QuizQuestionAdminView,
    QuizQuestionCreateRequest,
    QuizQuestionOption,
    QuizQuestionView,
    QuizResponse,
    QuizSubmitRequest,
    QuizzesPageResponse,
    SubmissionDownloadResponse,
    SurveyCreateRequest,
    SurveyListItem,
    SurveyQuestionCreateRequest,
    SurveyQuestionView,
    SurveyResponse_,
    SurveyResponseSubmitRequest,
    SurveysPageResponse,
    SurveyView,
    UngradedQuizAnswerItem,
    UngradedQuizAnswersResponse,
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


@router.get("/quizzes", response_model=QuizzesPageResponse)
async def list_quizzes(principal: PrincipalDep, session: SessionDep) -> QuizzesPageResponse:
    principal.require("course:edit")
    rows = await quiz_service.list_quizzes(session)
    return QuizzesPageResponse(
        items=[
            QuizListItem(
                id=str(q.id),
                title=q.title,
                pass_score=q.pass_score,
                max_attempts=q.max_attempts,
                time_limit_seconds=q.time_limit_seconds,
                question_count=count,
            )
            for q, count in rows
        ]
    )


@router.get("/quizzes/{quiz_id}", response_model=QuizDetailResponse)
async def get_quiz(
    quiz_id: str, principal: PrincipalDep, session: SessionDep
) -> QuizDetailResponse:
    # course:edit, not course:view — questions include `correct`, and the
    # seeded learner role holds course:view, so this must stay narrower.
    principal.require("course:edit")
    quiz, questions = await quiz_service.get_quiz_detail(session, quiz_id=_parse_uuid(quiz_id))
    return QuizDetailResponse(
        id=str(quiz.id),
        title=quiz.title,
        randomise_questions=quiz.randomise_questions,
        randomise_options=quiz.randomise_options,
        pass_score=quiz.pass_score,
        max_attempts=quiz.max_attempts,
        time_limit_seconds=quiz.time_limit_seconds,
        questions=[
            QuizQuestionAdminView(
                question_id=str(q.id),
                question_type=q.question_type,
                prompt=q.prompt,
                options=[QuizQuestionOption(**o) for o in q.options],
                position=q.position,
                points=q.points,
            )
            for q in questions
        ],
    )


@router.get("/quizzes/{quiz_id}/preview", response_model=QuizPreviewResponse)
async def preview_quiz(
    quiz_id: str, principal: PrincipalDep, session: SessionDep
) -> QuizPreviewResponse:
    """Any logged-in account, no purchase — gated on the quiz's lesson
    being a free preview (`access_level="public"`), not course:edit.
    Learner-shaped (no `correct`) and creates no `QuizAttempt`, unlike the
    real attempt flow."""
    quiz_uuid = _parse_uuid(quiz_id)
    # course:edit takes precedence over the enrolment/free-preview check —
    # an author previewing a draft lesson "as a learner" (the wizard's
    # view-as-learner) has no enrolment; same precedent as the survey
    # detail endpoint below. This shape carries no `correct` flags, so
    # nothing extra is exposed to an author who could read it anyway.
    if (
        "course:edit" not in principal.permissions
        and not await enrolment_service.has_view_access_to_quiz(
            session, tenant_id=principal.tenant_id, user_id=principal.user_id, quiz_id=quiz_uuid
        )
    ):
        raise Forbidden("This quiz is not available for preview.")
    quiz, questions = await quiz_service.get_quiz_detail(session, quiz_id=quiz_uuid)
    return QuizPreviewResponse(
        id=str(quiz.id),
        title=quiz.title,
        questions=[
            QuizQuestionView(**question_view(q, randomise_options=quiz.randomise_options))
            for q in questions
        ],
    )


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
        quiz_title=quiz.title,
        attempt_number=attempt.attempt_number,
        time_limit_seconds=quiz.time_limit_seconds,
        pass_score=quiz.pass_score,
        max_attempts=quiz.max_attempts,
        # attempt_number is the count of live attempts including this one
        # (services/quiz.py::start_attempt), so this is what remains after.
        attempts_remaining=max(0, quiz.max_attempts - attempt.attempt_number),
        randomise_questions=quiz.randomise_questions,
        randomise_options=quiz.randomise_options,
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


@router.get("/quiz-answers/ungraded", response_model=UngradedQuizAnswersResponse)
async def list_ungraded_quiz_answers(
    principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> UngradedQuizAnswersResponse:
    principal.require("quiz:grade")
    rows = await quiz_service.list_ungraded_answers(session, crypto, tenant_id=principal.tenant_id)
    return UngradedQuizAnswersResponse(
        items=[
            UngradedQuizAnswerItem(
                answer_id=str(r.answer_id),
                attempt_id=str(r.attempt_id),
                quiz_id=str(r.quiz_id),
                quiz_title=r.quiz_title,
                question_id=str(r.question_id),
                prompt=r.prompt,
                text_answer=r.text_answer,
                points_possible=r.points_possible,
                learner_email=r.learner_email,
                submitted_at=r.submitted_at,
            )
            for r in rows
        ]
    )


# ============================================================ Surveys ===


@router.get("/surveys", response_model=SurveysPageResponse)
async def list_surveys(principal: PrincipalDep, session: SessionDep) -> SurveysPageResponse:
    principal.require("course:edit")
    rows = await survey_service.list_surveys(session)
    return SurveysPageResponse(
        items=[
            SurveyListItem(
                id=str(s.id),
                title=s.title,
                response_mode=s.response_mode,
                minimum_group_size=s.minimum_group_size,
                question_count=count,
            )
            for s, count in rows
        ]
    )


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
    #
    # An authoring-capable caller doesn't need — and generally won't
    # have — an enrolment in whatever course this survey happens to be
    # attached to. course:edit is a strictly wider grant than "enrolled
    # learner" for read purposes here (no answer-key-equivalent field
    # exists on a survey question, unlike quizzes), so it takes
    # precedence over the enrolment check instead of requiring both. A
    # learner token never carries course:edit, so this is a no-op for
    # every existing learner-facing call site.
    #
    # has_view_access_to_survey, not resolve_enrolment_for_survey: this is
    # the one place a free-preview lesson's survey must also be readable
    # without a real enrolment (services/enrolment.py's own docstring).
    if (
        "course:edit" not in principal.permissions
        and not await enrolment_service.has_view_access_to_survey(
            session, tenant_id=principal.tenant_id, user_id=principal.user_id, survey_id=survey_uuid
        )
    ):
        raise Forbidden("You are not enrolled in this course.")
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


@router.get("/assignments", response_model=AssignmentsPageResponse)
async def list_assignments(principal: PrincipalDep, session: SessionDep) -> AssignmentsPageResponse:
    principal.require("course:edit")
    assignments = await assignment_service.list_assignments(session)
    return AssignmentsPageResponse(
        items=[
            AssignmentListItem(
                id=str(a.id),
                title=a.title,
                max_score=a.max_score,
                approval_required=a.approval_required,
            )
            for a in assignments
        ]
    )


@router.get("/assignments/{assignment_id}", response_model=AssignmentDetailResponse)
async def get_assignment(
    assignment_id: str, principal: PrincipalDep, session: SessionDep
) -> AssignmentDetailResponse:
    principal.require("course:edit")
    assignment = await assignment_service.get_assignment(
        session, assignment_id=_parse_uuid(assignment_id)
    )
    return AssignmentDetailResponse(
        id=str(assignment.id),
        title=assignment.title,
        instructions=assignment.instructions,
        max_score=assignment.max_score,
        approval_required=assignment.approval_required,
    )


@router.get("/assignments/{assignment_id}/preview", response_model=AssignmentDetailResponse)
async def preview_assignment(
    assignment_id: str, principal: PrincipalDep, session: SessionDep
) -> AssignmentDetailResponse:
    """Any logged-in account, no purchase — gated on the assignment's
    lesson being a free preview. Same response shape as the course:edit
    -gated detail endpoint above; the gate is what differs, not the data
    (an assignment carries no answer-key-equivalent field to withhold).
    A side effect worth noting, not a scope expansion: this is also the
    first endpoint letting an *enrolled* learner read an assignment's
    instructions at all — nothing previously exposed that outside
    authoring."""
    assignment_uuid = _parse_uuid(assignment_id)
    if (
        "course:edit" not in principal.permissions
        and not await enrolment_service.has_view_access_to_assignment(
            session,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            assignment_id=assignment_uuid,
        )
    ):
        raise Forbidden("This assignment is not available for preview.")
    assignment = await assignment_service.get_assignment(session, assignment_id=assignment_uuid)
    return AssignmentDetailResponse(
        id=str(assignment.id),
        title=assignment.title,
        instructions=assignment.instructions,
        max_score=assignment.max_score,
        approval_required=assignment.approval_required,
    )


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
        f"{uuid.uuid4().hex}-{safe_filename(filename, fallback='submission')}"
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


@router.get("/assignment-submissions/pending", response_model=PendingSubmissionsResponse)
async def list_pending_assignment_submissions(
    principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> PendingSubmissionsResponse:
    principal.require("quiz:grade")
    rows = await assignment_service.list_pending_submissions(
        session, crypto, tenant_id=principal.tenant_id
    )
    return PendingSubmissionsResponse(
        items=[
            PendingSubmissionItem(
                submission_id=str(r.submission_id),
                assignment_id=str(r.assignment_id),
                assignment_title=r.assignment_title,
                learner_email=r.learner_email,
                version=r.version,
                submitted_at=r.submitted_at,
            )
            for r in rows
        ]
    )


@router.get(
    "/assignment-submissions/{submission_id}/download", response_model=SubmissionDownloadResponse
)
async def download_assignment_submission(
    submission_id: str, principal: PrincipalDep, session: SessionDep, storage: StorageDep
) -> SubmissionDownloadResponse:
    principal.require("quiz:grade")
    submission = await session.get(AssignmentSubmission, _parse_uuid(submission_id))
    if submission is None or submission.tenant_id != principal.tenant_id:
        raise NotFound("No such submission.")
    url = await storage.generate_signed_url(
        Container.USER_UPLOADS, submission.object_key, expires_in=300
    )
    return SubmissionDownloadResponse(download_url=url)


__all__ = ["router"]
