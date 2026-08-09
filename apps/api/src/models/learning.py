"""Learning (02 §7): the authoritative progress record. Tenant-scoped and
RLS-bound, unlike the course catalogue it points at — an enrolment belongs
to one tenant's paying learner, even though the course itself is shared.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

LESSON_STATE_VALUES = ("locked", "available", "in_progress", "requirements_met", "completed")

# create_type=False: see commerce.py's OrderStatus for why.
LessonState = Enum(*LESSON_STATE_VALUES, name="lesson_state", create_type=False)


class Enrolment(Base, TimestampMixin):
    """Joins a user to a course, sourced from an entitlement (02 §7.1) —
    created in the same transaction as the entitlement grant
    (services/orders.py::approve_eft), never independently."""

    __tablename__ = "enrolments"
    __table_args__ = (
        Index("uq_enrolments_tenant_user_course", "tenant_id", "user_id", "course_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entitlement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entitlements.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # No cohort table yet (02 §13 lists cohort definition as an open
    # question) — nullable and un-constrained on purpose, a forward-
    # compatible placeholder rather than a guessed FK.
    cohort_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class LessonCompletion(Base, TimestampMixin):
    """The authoritative progress record (02 §7.2, REQ-BYPASS-01). A row
    exists only once a learner has actually started a lesson
    (POST /lessons/{id}/start) — 'locked'/'available' are computed on read
    for lessons with no row yet (services/completion.py::get_progress),
    not eagerly materialised for every lesson at enrolment time.
    """

    __tablename__ = "lesson_completions"
    __table_args__ = (
        Index("uq_lesson_completions_enrolment_lesson", "enrolment_id", "lesson_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("enrolments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lessons.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(LessonState, nullable=False, server_default="in_progress")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accumulated_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # A snapshot of which requirements were met and which were not, at the
    # moment of the decision (services/completion.py::RuleEvaluation) —
    # what makes a completion dispute resolvable after the fact.
    rule_evaluation: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


__all__ = ["Enrolment", "LessonCompletion", "LessonState"]
