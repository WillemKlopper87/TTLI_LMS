"""Manager visibility (02 §4.5, REQ-TEN-03, 04 §2.3's P2 policy).

Aggregate-only by default. Individual *scores* require all three
conditions at once — course-level toggle, tenant-level setting, and the
viewer holding a real grant.

What "aggregate only" withholds narrowed deliberately with the manager
dashboard: the participation list is now always returned, and it is the
**score** that is withheld (`best_quiz_score: null`, `score_hidden:
true`), not the row. The earlier all-or-nothing rule dropped the rows
entirely, which made a seat-management screen impossible to build — a
manager who bought and assigned the seats could not see whether the
people they assigned them to had started. Identity in a withheld row is
still protected: `display_name` falls back to a masked email
(`t•••@meridian.co.za`) and the real address is only ever populated when
individual visibility is on. What REQ-TEN-03 exists to stop is a manager
ranking their team by score; participation without a score does not
enable that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.deps import Principal
from src.core.errors import NotFound
from src.models.assessment import QuizAttempt
from src.models.commerce import Entitlement
from src.models.course import Course, Lesson, Module
from src.models.learning import Enrolment, LessonCompletion
from src.models.tenant import Tenant
from src.models.user import User
from src.services import organisations as organisations_service

PERMISSION_VIEW_INDIVIDUAL = "team:reports:view_individual"


AT_RISK_DAYS = 14
AT_RISK_PROGRESS_PERCENT = 25


@dataclass(frozen=True, slots=True)
class LearnerRow:
    user_id: uuid.UUID
    email: str
    display_name: str
    status: str  # "not_started" | "in_progress" | "completed"
    progress_percent: int
    last_active_at: datetime | None
    completed_at: datetime | None
    best_quiz_score: Decimal | None
    score_hidden: bool


@dataclass(frozen=True, slots=True)
class ProgressReport:
    course_id: uuid.UUID
    course_title: str
    enrolled: int
    completed: int
    completion_rate: float
    average_progress: int
    at_risk: int
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


async def _best_quiz_scores_by_enrolment(
    session: AsyncSession, *, enrolment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """enrolment_id -> best submitted score. One grouped read rather than
    one query per learner, same reasoning as `_activity_by_enrolment` —
    this only runs at all when `individual_visible`, but a privileged
    viewer's organisation can still have many seats."""
    if not enrolment_ids:
        return {}
    stmt = (
        select(QuizAttempt.enrolment_id, func.max(QuizAttempt.score))
        .where(
            QuizAttempt.enrolment_id.in_(enrolment_ids),
            QuizAttempt.submitted_at.is_not(None),
            QuizAttempt.score.is_not(None),
        )
        .group_by(QuizAttempt.enrolment_id)
    )
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


def _status(enrolment: Enrolment) -> str:
    if enrolment.completed_at is not None:
        return "completed"
    if enrolment.started_at is not None:
        return "in_progress"
    return "not_started"


def _mask_email(email: str) -> str:
    """`thabo@meridian.co.za` -> `t•••@meridian.co.za`. The domain stays
    readable on purpose — it identifies an employer, not a person (the
    same reasoning `models/user.py` keeps `email_domain` in clear for)."""
    local, _, domain = email.partition("@")
    initial = local[:1] or "•"
    return f"{initial}•••@{domain}" if domain else f"{initial}•••"


async def _lesson_total(session: AsyncSession, *, course_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course_id)
    )
    return int((await session.execute(stmt)).scalar_one())


async def _activity_by_enrolment(
    session: AsyncSession, *, enrolment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, datetime | None]]:
    """enrolment_id -> (completed lesson count, last touched). One grouped
    read rather than two queries per learner — a manager's report covers
    a whole organisation's seats."""
    if not enrolment_ids:
        return {}
    stmt = (
        select(
            LessonCompletion.enrolment_id,
            func.count().filter(LessonCompletion.state == "completed"),
            func.max(LessonCompletion.updated_at),
        )
        .where(LessonCompletion.enrolment_id.in_(enrolment_ids))
        .group_by(LessonCompletion.enrolment_id)
    )
    return {row[0]: (int(row[1]), row[2]) for row in (await session.execute(stmt)).all()}


def _is_at_risk(
    enrolment: Enrolment, *, progress_percent: int, last_active_at: datetime | None, now: datetime
) -> bool:
    """Two distinct failure modes, both worth a manager's attention: a
    seat assigned a fortnight ago that was never opened, and a learner
    who opened the course, barely moved, and has since gone quiet. A
    finished learner is never at risk regardless of dates."""
    if enrolment.completed_at is not None:
        return False
    if enrolment.started_at is None:
        return (now - enrolment.created_at) >= timedelta(days=AT_RISK_DAYS)
    if progress_percent < AT_RISK_PROGRESS_PERCENT:
        reference = last_active_at or enrolment.started_at
        return (now - reference) >= timedelta(days=AT_RISK_DAYS)
    return False


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
            # Belt-and-braces alongside RLS (`core/db.py`'s `SET LOCAL
            # app.tenant_id`, which already fails a forgotten predicate
            # closed rather than open) — explicit here too since this is
            # exactly the kind of reporting query that comment warns about.
            Entitlement.tenant_id == tenant_id,
            Enrolment.tenant_id == tenant_id,
            User.tenant_id == tenant_id,
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

    lessons_total = await _lesson_total(session, course_id=course_id)
    enrolment_ids = [enrolment.id for _, enrolment, _ in rows]
    activity = await _activity_by_enrolment(session, enrolment_ids=enrolment_ids)
    best_scores = (
        await _best_quiz_scores_by_enrolment(session, enrolment_ids=enrolment_ids)
        if individual_visible
        else {}
    )
    now = datetime.now(UTC)

    learner_list: list[LearnerRow] = []
    at_risk = 0
    for _, enrolment, user in rows:
        lessons_completed, last_active_at = activity.get(enrolment.id, (0, None))
        progress_percent = round(100 * lessons_completed / lessons_total) if lessons_total else 0
        if enrolment.completed_at is not None:
            progress_percent = 100
        if _is_at_risk(
            enrolment,
            progress_percent=progress_percent,
            last_active_at=last_active_at,
            now=now,
        ):
            at_risk += 1

        email = crypto.decrypt(user.email_encrypted)
        # Never the real address, and never the real name, in a
        # score-hidden report — the participation row proves membership,
        # which the manager already knows (they assigned the seat), not
        # an identity they could not otherwise resolve. `display_name`
        # must degrade exactly like `email` does: a decrypted full name
        # is a *more* identifying leak than the address it would
        # otherwise fall back to, not a less sensitive one, so it can
        # never bypass the same `individual_visible` gate.
        email_display = email if individual_visible else _mask_email(email)
        full_name = (
            crypto.decrypt(user.full_name_encrypted)
            if individual_visible and user.full_name_encrypted
            else None
        )
        learner_list.append(
            LearnerRow(
                user_id=user.id,
                email=email_display,
                display_name=full_name or email_display,
                status=_status(enrolment),
                progress_percent=progress_percent,
                last_active_at=last_active_at or enrolment.started_at,
                completed_at=enrolment.completed_at,
                best_quiz_score=best_scores.get(enrolment.id) if individual_visible else None,
                score_hidden=not individual_visible,
            )
        )
    learners: tuple[LearnerRow, ...] = tuple(learner_list)
    average_progress = (
        round(sum(row.progress_percent for row in learners) / len(learners)) if learners else 0
    )

    return ProgressReport(
        course_id=course_id,
        course_title=course.title,
        enrolled=enrolled,
        completed=completed,
        completion_rate=completion_rate,
        average_progress=average_progress,
        at_risk=at_risk,
        individual_visible=individual_visible,
        learners=learners,
    )


__all__ = [
    "AT_RISK_DAYS",
    "AT_RISK_PROGRESS_PERCENT",
    "PERMISSION_VIEW_INDIVIDUAL",
    "LearnerRow",
    "ProgressReport",
    "get_progress_report",
]
