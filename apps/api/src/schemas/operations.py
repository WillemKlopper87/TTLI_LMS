"""Operations overview and per-course analytics response shapes
(`docs/research/enterprise-gaps-plan.md` Pass A, gaps #41 and #40).

Two reads that answer two different questions:

* `OverviewResponse` — "what needs a human today?" Counts a manager
  scans in two seconds, plus the short lists behind them. Every figure
  is a live aggregate; nothing is cached or precomputed.
* `CourseAnalyticsResponse` — "is this course working?" The enrolment
  funnel, where learners stop, and how the assessment behaved.

Money follows `schemas/analytics.py`'s rule exactly: always a list per
currency, never a blended total, because this platform sells in more
than one currency and a summed figure would be a fabrication.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.schemas.analytics import MoneyByCurrency


class AttentionOrderRow(BaseModel):
    """An order sitting in a state only a human can move on."""

    order_id: uuid.UUID
    order_number: str
    status: str
    currency: str
    grand_total: float
    buyer_email: str | None
    waiting_since: datetime
    hours_waiting: int


class AttentionSubmissionRow(BaseModel):
    submission_id: uuid.UUID
    enrolment_id: uuid.UUID
    assignment_title: str
    course_title: str
    submitted_at: datetime
    hours_waiting: int


class AttentionTranscodeRow(BaseModel):
    transcode_job_id: uuid.UUID
    video_asset_id: uuid.UUID
    lesson_title: str | None
    course_title: str | None
    error: str | None
    failed_at: datetime | None


class AtRiskLearnerRow(BaseModel):
    """Deliberately masked, like `services/reports.py` does: an operations
    dashboard needs to know *that* someone is stalling and in which
    course, not who they are — the manager-visibility rules in
    REQ-TEN-03 govern naming a learner, and this screen does not carry
    that gate."""

    enrolment_id: uuid.UUID
    course_id: uuid.UUID
    course_title: str
    learner_reference: str
    progress_percent: int
    last_active_at: datetime | None
    days_inactive: int


class OverviewKpis(BaseModel):
    revenue_mtd: list[MoneyByCurrency]
    active_learners: int
    pending_approvals: int
    completions_this_month: int
    certificates_issued_this_month: int
    upcoming_sessions: int
    at_risk_learners: int


class OverviewResponse(BaseModel):
    generated_at: datetime
    month_start: datetime
    kpis: OverviewKpis
    payment_approvals: list[AttentionOrderRow]
    ungraded_submissions: list[AttentionSubmissionRow]
    failed_transcodes: list[AttentionTranscodeRow]
    at_risk: list[AtRiskLearnerRow]


class CourseFunnel(BaseModel):
    """Three states an enrolment can be in, and they nest: every started
    enrolment was enrolled, every completed one was started."""

    enrolled: int
    started: int
    completed: int


class LessonDropoffRow(BaseModel):
    lesson_id: uuid.UUID
    title: str
    position: int
    module_title: str
    reached: int
    completed: int
    completion_rate: float


class QuizScoreRow(BaseModel):
    quiz_id: uuid.UUID
    lesson_title: str
    attempts: int
    average_score: float | None
    pass_rate: float | None
    # Five 20-point buckets, lowest first. A histogram is what makes a
    # badly-calibrated quiz visible; an average alone hides bimodality.
    score_buckets: list[int]


class CourseAnalyticsResponse(BaseModel):
    course_id: uuid.UUID
    course_title: str
    generated_at: datetime
    funnel: CourseFunnel
    completion_rate: float
    median_days_to_complete: float | None
    lesson_dropoff: list[LessonDropoffRow]
    quiz_scores: list[QuizScoreRow]
    at_risk: list[AtRiskLearnerRow]


class CourseSummaryRow(BaseModel):
    """One row of the course list the reports screen opens on."""

    course_id: uuid.UUID
    title: str
    state: str
    enrolled: int
    completed: int
    completion_rate: float
    at_risk: int


class CourseSummaryResponse(BaseModel):
    generated_at: datetime
    courses: list[CourseSummaryRow]


__all__ = [
    "AtRiskLearnerRow",
    "AttentionOrderRow",
    "AttentionSubmissionRow",
    "AttentionTranscodeRow",
    "CourseAnalyticsResponse",
    "CourseFunnel",
    "CourseSummaryResponse",
    "CourseSummaryRow",
    "LessonDropoffRow",
    "OverviewKpis",
    "OverviewResponse",
    "QuizScoreRow",
]
