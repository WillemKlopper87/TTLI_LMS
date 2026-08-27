"""Quizzes, surveys, assignments (02 §7.5/7.6/7.7). See 0013's migration
docstring for the anonymous-survey blind-index design and the tenant-
scoping split (global question banks, tenant-scoped attempts/responses/
submissions — same shape as courses/video_assets vs. enrolments/
video_progress).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

SURVEY_RESPONSE_MODE_VALUES = ("identified", "anonymous")
SurveyResponseMode = Enum(
    *SURVEY_RESPONSE_MODE_VALUES, name="survey_response_mode", create_type=False
)
SURVEY_EVALUATION_ROLE_VALUES = ("standalone", "pre", "post")
SurveyEvaluationRole = Enum(
    *SURVEY_EVALUATION_ROLE_VALUES, name="survey_evaluation_role", create_type=False
)


class Quiz(Base, TimestampMixin):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    randomise_questions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    randomise_options: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    pass_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("70"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[uuid.UUID] = pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (Index("ix_quiz_attempts_enrolment_quiz", "enrolment_id", "quiz_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("enrolments.id", ondelete="CASCADE"), nullable=False
    )
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_order: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quiz_questions.id", ondelete="RESTRICT"), nullable=False
    )
    selected_option_ids: Mapped[list[object] | None] = mapped_column(JSONB, nullable=True)
    text_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    points_awarded: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)


class Survey(Base, TimestampMixin):
    __tablename__ = "surveys"
    __table_args__ = (
        CheckConstraint(
            "(evaluation_role = 'standalone' AND pair_id IS NULL) OR "
            "(evaluation_role IN ('pre', 'post') AND pair_id IS NOT NULL)",
            name="ck_surveys_evaluation_pair",
        ),
        Index(
            "uq_surveys_pair_pre",
            "pair_id",
            unique=True,
            postgresql_where=text("evaluation_role = 'pre'"),
        ),
        Index(
            "uq_surveys_pair_post",
            "pair_id",
            unique=True,
            postgresql_where=text("evaluation_role = 'post'"),
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    response_mode: Mapped[str] = mapped_column(SurveyResponseMode, nullable=False)
    minimum_group_size: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    evaluation_role: Mapped[str] = mapped_column(
        SurveyEvaluationRole, nullable=False, server_default=text("'standalone'")
    )
    pair_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class SurveyQuestion(Base):
    __tablename__ = "survey_questions"

    id: Mapped[uuid.UUID] = pk()
    survey_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class SurveyResponse(Base):
    """`user_id` and `respondent_reference` are mutually exclusive
    (`ck_survey_responses_one_subject`, 0013) — an anonymous response
    never carries anything that identifies who submitted it."""

    __tablename__ = "survey_responses"
    __table_args__ = (
        Index(
            "uq_survey_responses_survey_reference",
            "survey_id",
            "respondent_reference",
            unique=True,
        ),
        Index("uq_survey_responses_survey_user", "survey_id", "user_id", unique=True),
        # Created via raw SQL in 0013 (op.execute, not a declarative
        # CheckConstraint) — declared here too so alembic's autogenerate
        # can see it. A newer alembic (dependency-upgrade sprint B) added
        # real comparison for exactly this, surfacing a gap between this
        # model and the database that existed since 0013 but was
        # previously invisible to `alembic check`.
        CheckConstraint(
            "(user_id IS NULL) <> (respondent_reference IS NULL)",
            name="ck_survey_responses_one_subject",
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    survey_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("surveys.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    respondent_reference: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    answers: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class AssignmentSubmission(Base):
    __tablename__ = "assignment_submissions"
    __table_args__ = (
        Index("ix_assignment_submissions_enrolment_assignment", "enrolment_id", "assignment_id"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("enrolments.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assignments.id", ondelete="RESTRICT"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scan_result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = [
    "Assignment",
    "AssignmentSubmission",
    "Quiz",
    "QuizAnswer",
    "QuizAttempt",
    "QuizQuestion",
    "Survey",
    "SurveyEvaluationRole",
    "SurveyQuestion",
    "SurveyResponse",
    "SurveyResponseMode",
]
