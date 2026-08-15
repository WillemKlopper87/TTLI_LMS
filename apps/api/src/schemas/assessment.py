from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# --- Quizzes ---
class QuizQuestionOption(BaseModel):
    id: str
    text: str
    correct: bool = False


class QuizCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    randomise_questions: bool = False
    randomise_options: bool = False
    pass_score: int = Field(default=70, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1)
    time_limit_seconds: int | None = Field(default=None, ge=1)


class QuizResponse(BaseModel):
    id: str
    title: str


class QuizQuestionCreateRequest(BaseModel):
    question_type: str
    prompt: str = Field(min_length=1)
    options: list[QuizQuestionOption] = Field(default_factory=list)
    position: int
    points: int = Field(default=1, ge=1)


class QuizQuestionView(BaseModel):
    """Learner-facing — never includes which options are correct."""

    question_id: str
    question_type: str
    prompt: str
    options: list[dict[str, str]]
    points: int


class QuizAttemptResponse(BaseModel):
    attempt_id: str
    quiz_id: str
    attempt_number: int
    time_limit_seconds: int | None
    questions: list[QuizQuestionView]


class QuizAnswerSubmission(BaseModel):
    question_id: str
    selected_option_ids: list[str] | None = None
    text_answer: str | None = None


class QuizSubmitRequest(BaseModel):
    answers: list[QuizAnswerSubmission]


class QuizAttemptResult(BaseModel):
    attempt_id: str
    submitted_at: datetime
    score: Decimal
    passed: bool | None


class QuizGradeRequest(BaseModel):
    points_awarded: Decimal = Field(ge=0)


class QuizListItem(BaseModel):
    id: str
    title: str
    pass_score: int
    max_attempts: int
    time_limit_seconds: int | None
    question_count: int


class QuizzesPageResponse(BaseModel):
    items: list[QuizListItem]


class QuizQuestionAdminView(BaseModel):
    """Authoring-facing — unlike `QuizQuestionView`, this DOES include
    which option is `correct`. Gated at `course:edit`, never `course:view`
    — the seeded `learner` role holds `course:view`, so this must never
    be reachable with only that permission."""

    question_id: str
    question_type: str
    prompt: str
    options: list[QuizQuestionOption]
    position: int
    points: int


class QuizDetailResponse(BaseModel):
    id: str
    title: str
    randomise_questions: bool
    randomise_options: bool
    pass_score: int
    max_attempts: int
    time_limit_seconds: int | None
    questions: list[QuizQuestionAdminView]


class UngradedQuizAnswerItem(BaseModel):
    answer_id: str
    attempt_id: str
    quiz_id: str
    quiz_title: str
    question_id: str
    prompt: str
    text_answer: str
    points_possible: int
    learner_email: str
    submitted_at: datetime


class UngradedQuizAnswersResponse(BaseModel):
    items: list[UngradedQuizAnswerItem]


# --- Surveys ---
class SurveyQuestionOption(BaseModel):
    id: str
    text: str


class SurveyCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    response_mode: str = Field(pattern="^(identified|anonymous)$")
    minimum_group_size: int = Field(default=5, ge=1)


class SurveyResponse_(BaseModel):
    id: str
    title: str
    response_mode: str


class SurveyQuestionCreateRequest(BaseModel):
    question_type: str
    prompt: str = Field(min_length=1)
    options: list[SurveyQuestionOption] = Field(default_factory=list)
    position: int


class SurveyQuestionView(BaseModel):
    question_id: str
    question_type: str
    prompt: str
    options: list[dict[str, str]]


class SurveyView(BaseModel):
    survey_id: str
    title: str
    response_mode: str
    questions: list[SurveyQuestionView]


class SurveyAnswer(BaseModel):
    question_id: str
    value: str


class SurveyResponseSubmitRequest(BaseModel):
    answers: list[SurveyAnswer]


class SurveyListItem(BaseModel):
    id: str
    title: str
    response_mode: str
    minimum_group_size: int
    question_count: int


class SurveysPageResponse(BaseModel):
    items: list[SurveyListItem]


# --- Assignments ---
class AssignmentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    instructions: str | None = None
    max_score: int = Field(default=100, ge=1)
    approval_required: bool = True


class AssignmentResponse(BaseModel):
    id: str
    title: str


class AssignmentSubmissionResponse(BaseModel):
    id: str
    version: int
    submitted_at: datetime
    approved_at: datetime | None
    rejected_reason: str | None


class AssignmentReviewRequest(BaseModel):
    approve: bool
    rejected_reason: str | None = None


class AssignmentListItem(BaseModel):
    id: str
    title: str
    max_score: int
    approval_required: bool


class AssignmentsPageResponse(BaseModel):
    items: list[AssignmentListItem]


class AssignmentDetailResponse(BaseModel):
    id: str
    title: str
    instructions: str | None
    max_score: int
    approval_required: bool


class PendingSubmissionItem(BaseModel):
    submission_id: str
    assignment_id: str
    assignment_title: str
    learner_email: str
    version: int
    submitted_at: datetime


class PendingSubmissionsResponse(BaseModel):
    items: list[PendingSubmissionItem]


class SubmissionDownloadResponse(BaseModel):
    download_url: str


__all__ = [
    "AssignmentCreateRequest",
    "AssignmentDetailResponse",
    "AssignmentListItem",
    "AssignmentResponse",
    "AssignmentReviewRequest",
    "AssignmentSubmissionResponse",
    "AssignmentsPageResponse",
    "PendingSubmissionItem",
    "PendingSubmissionsResponse",
    "QuizAnswerSubmission",
    "QuizAttemptResponse",
    "QuizAttemptResult",
    "QuizCreateRequest",
    "QuizDetailResponse",
    "QuizGradeRequest",
    "QuizListItem",
    "QuizQuestionAdminView",
    "QuizQuestionCreateRequest",
    "QuizQuestionOption",
    "QuizQuestionView",
    "QuizResponse",
    "QuizSubmitRequest",
    "QuizzesPageResponse",
    "SubmissionDownloadResponse",
    "SurveyAnswer",
    "SurveyCreateRequest",
    "SurveyListItem",
    "SurveyQuestionCreateRequest",
    "SurveyQuestionOption",
    "SurveyQuestionView",
    "SurveyResponseSubmitRequest",
    "SurveyResponse_",
    "SurveyView",
    "SurveysPageResponse",
    "UngradedQuizAnswerItem",
    "UngradedQuizAnswersResponse",
]
