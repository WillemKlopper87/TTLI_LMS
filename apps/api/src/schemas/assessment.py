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


__all__ = [
    "AssignmentCreateRequest",
    "AssignmentResponse",
    "AssignmentReviewRequest",
    "AssignmentSubmissionResponse",
    "QuizAnswerSubmission",
    "QuizAttemptResponse",
    "QuizAttemptResult",
    "QuizCreateRequest",
    "QuizGradeRequest",
    "QuizQuestionCreateRequest",
    "QuizQuestionOption",
    "QuizQuestionView",
    "QuizResponse",
    "QuizSubmitRequest",
    "SurveyAnswer",
    "SurveyCreateRequest",
    "SurveyQuestionCreateRequest",
    "SurveyQuestionOption",
    "SurveyQuestionView",
    "SurveyResponseSubmitRequest",
    "SurveyResponse_",
    "SurveyView",
]
