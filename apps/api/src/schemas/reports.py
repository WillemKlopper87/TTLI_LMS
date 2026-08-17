from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class LearnerRowResponse(BaseModel):
    """One assigned seat. Always present — participation is not the thing
    REQ-TEN-03 withholds; the *score* is (`score_hidden`, and
    `best_quiz_score` null with it). `email` is masked, and `display_name`
    falls back to that mask, whenever the score is hidden."""

    user_id: str
    email: str
    display_name: str
    status: str
    progress_percent: int
    last_active_at: datetime | None
    completed_at: datetime | None
    best_quiz_score: Decimal | None
    score_hidden: bool


class ProgressReportResponse(BaseModel):
    course_id: str
    course_title: str
    enrolled: int
    completed: int
    completion_rate: float
    average_progress: int
    at_risk: int
    individual_visible: bool
    learners: list[LearnerRowResponse]


__all__ = ["LearnerRowResponse", "ProgressReportResponse"]
