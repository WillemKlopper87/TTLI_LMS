from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class LearnerRowResponse(BaseModel):
    user_id: str
    email: str
    status: str
    completed_at: datetime | None
    best_quiz_score: Decimal | None


class ProgressReportResponse(BaseModel):
    course_id: str
    course_title: str
    enrolled: int
    completed: int
    completion_rate: float
    individual_visible: bool
    learners: list[LearnerRowResponse]


__all__ = ["LearnerRowResponse", "ProgressReportResponse"]
