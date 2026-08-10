"""Manager visibility (02 §4.5, REQ-TEN-03, 04 §2.3's P2 policy).

Aggregate-only by default. Individual rows require all three conditions
at once — course-level toggle, tenant-level setting, and the viewer
holding a real grant — and "aggregate only" means individual rows are
**absent from the response**, not present and redacted (03 §9): a
redacted row would still confirm a person exists and did not complete
something, which is exactly the bullying-enabling leak REQ-TEN-03 exists
to close.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.deps import Principal
from src.core.errors import NotFound
from src.models.assessment import QuizAttempt
from src.models.commerce import Entitlement
from src.models.course import Course
from src.models.learning import Enrolment
from src.models.tenant import Tenant
from src.models.user import User
from src.services import organisations as organisations_service

PERMISSION_VIEW_INDIVIDUAL = "team:reports:view_individual"


@dataclass(frozen=True, slots=True)
class LearnerRow:
    user_id: uuid.UUID
    email: str
    status: str  # "not_started" | "in_progress" | "completed"
    completed_at: datetime | None
    best_quiz_score: Decimal | None


@dataclass(frozen=True, slots=True)
class ProgressReport:
    course_id: uuid.UUID
    course_title: str
    enrolled: int
    completed: int
    completion_rate: float
    individual_visible: bool
    learners: tuple[LearnerRow, ...]


async def _can_view_individual(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    principal: Principal,
    organisation_id: uuid.UUID,
    course: Course,
) -> bool:
    if course.manager_visibility != "individual_enabled":
        return False

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or not tenant.settings.get("allow_manager_individual_results"):
        return False

    if PERMISSION_VIEW_INDIVIDUAL in principal.permissions:
        return True

    relationship = await organisations_service.get_relationship(
        session, organisation_id=organisation_id, user_id=principal.user_id
    )
    return relationship in ("manager", "admin")


async def _best_quiz_score(session: AsyncSession, *, enrolment_id: uuid.UUID) -> Decimal | None:
    stmt = select(QuizAttempt.score).where(
        QuizAttempt.enrolment_id == enrolment_id,
        QuizAttempt.submitted_at.is_not(None),
        QuizAttempt.score.is_not(None),
    )
    scores = [s for s in (await session.execute(stmt)).scalars().all() if s is not None]
    return max(scores) if scores else None


def _status(enrolment: Enrolment) -> str:
    if enrolment.completed_at is not None:
        return "completed"
    if enrolment.started_at is not None:
        return "in_progress"
    return "not_started"


async def get_progress_report(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    principal: Principal,
    organisation_id: uuid.UUID,
    course_id: uuid.UUID,
) -> ProgressReport:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFound("No such course.")

    # Every seat this organisation has assigned (not revoked) for this
    # course, joined to that learner's own enrolment — the same pool/
    # assigned-seat model 0016 built, read here rather than re-derived.
    stmt = (
        select(Entitlement, Enrolment, User)
        .join(
            Enrolment,
            and_(
                Enrolment.user_id == Entitlement.user_id,
                Enrolment.course_id == Entitlement.target_id,
            ),
        )
        .join(User, User.id == Entitlement.user_id)
        .where(
            Entitlement.organisation_id == organisation_id,
            Entitlement.target_id == course_id,
            Entitlement.kind == "course",
            Entitlement.user_id.is_not(None),
            Entitlement.revoked_at.is_(None),
        )
    )
    rows = (await session.execute(stmt)).all()

    enrolled = len(rows)
    completed = sum(1 for _, enrolment, _ in rows if enrolment.completed_at is not None)
    completion_rate = (completed / enrolled) if enrolled else 0.0

    individual_visible = await _can_view_individual(
        session,
        tenant_id=tenant_id,
        principal=principal,
        organisation_id=organisation_id,
        course=course,
    )

    learner_list: list[LearnerRow] = []
    if individual_visible:
        for _, enrolment, user in rows:
            learner_list.append(
                LearnerRow(
                    user_id=user.id,
                    email=crypto.decrypt(user.email_encrypted),
                    status=_status(enrolment),
                    completed_at=enrolment.completed_at,
                    best_quiz_score=await _best_quiz_score(session, enrolment_id=enrolment.id),
                )
            )
    learners: tuple[LearnerRow, ...] = tuple(learner_list)

    return ProgressReport(
        course_id=course_id,
        course_title=course.title,
        enrolled=enrolled,
        completed=completed,
        completion_rate=completion_rate,
        individual_visible=individual_visible,
        learners=learners,
    )


__all__ = [
    "PERMISSION_VIEW_INDIVIDUAL",
    "LearnerRow",
    "ProgressReport",
    "get_progress_report",
]
