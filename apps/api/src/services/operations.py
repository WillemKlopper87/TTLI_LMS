"""Operations overview and per-course analytics (`docs/research/
enterprise-gaps-plan.md` Pass A — feature-matrix gaps #41 and #40).

Read-only and tenant-scoped, exactly like `services/analytics.py`: every
function takes an explicit `tenant_id` and filters on it on top of the
RLS the session already carries. Nothing here writes.

Two deliberate reuses rather than reimplementations:

* **Revenue MTD** comes from `analytics.actual_revenue` over a
  month-to-date `Period`, so the number on the admin home and the number
  on the revenue dashboard can never disagree — Pass A's own
  instruction ("reuses the payment/revenue analytics endpoints rather
  than duplicating them").
* **At risk** uses `reports._is_at_risk`, the same two-failure-mode rule
  (never opened in AT_RISK_DAYS; opened, under AT_RISK_PROGRESS_PERCENT,
  then quiet) the manager report already applies. A second definition of
  "at risk" in the same product would be a bug waiting to be argued
  about.

Learner identity is masked here (`reports._mask_email`) even though the
caller holds `analytics:view`: REQ-TEN-03's manager-visibility rules
govern naming a learner, this screen carries no such gate, and an
operations dashboard needs to know *that* someone is stalling, not who.

Courses are not tenant-scoped rows — `courses` is a global catalogue and
`course_tenant_assignments` is what makes one visible to a tenant
(`models/course.py`). Every course query below therefore joins that
assignment table rather than filtering a `courses.tenant_id` that does
not exist.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.models.assessment import AssignmentSubmission, Quiz, QuizAttempt
from src.models.commerce import Order
from src.models.course import Course, CourseTenantAssignment, Lesson, Module
from src.models.credential import Certificate
from src.models.learning import Enrolment, LessonCompletion
from src.models.media import TranscodeJob, VideoAsset
from src.models.user import User
from src.models.workshop import WorkshopSession
from src.schemas.operations import (
    AtRiskLearnerRow,
    AttentionOrderRow,
    AttentionSubmissionRow,
    AttentionTranscodeRow,
    CourseAnalyticsResponse,
    CourseFunnel,
    CourseSummaryResponse,
    CourseSummaryRow,
    LessonDropoffRow,
    OverviewKpis,
    OverviewResponse,
    QuizScoreRow,
)
from src.services import analytics as analytics_service
from src.services.reports import (
    _activity_by_enrolment,
    _is_at_risk,
    _lesson_total,
    _mask_email,
)

# Orders whose next move is a human decision. These are exactly the
# states `routers/orders.py`'s approve/reject pair accepts, so the count
# on the dashboard equals the size of the finance queue, not an
# approximation of it.
AWAITING_HUMAN = ("eft_pending_approval", "po_pending_approval")

# How many rows each "needs attention" list carries. A dashboard is a
# prompt to act, not a work queue — the real queues are /admin/payments
# and /admin/grading, which these lists link to.
ATTENTION_LIMIT = 8


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _tenant_courses(tenant_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return select(CourseTenantAssignment.course_id).where(
        CourseTenantAssignment.tenant_id == tenant_id
    )


async def _payment_approvals(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, now: datetime
) -> tuple[int, list[AttentionOrderRow]]:
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Order)
                .where(Order.tenant_id == tenant_id, Order.status.in_(AWAITING_HUMAN))
            )
        ).scalar_one()
    )
    rows = (
        await session.execute(
            select(Order, User.email_encrypted)
            .join(User, User.id == Order.user_id)
            .where(Order.tenant_id == tenant_id, Order.status.in_(AWAITING_HUMAN))
            .order_by(Order.updated_at)
            .limit(ATTENTION_LIMIT)
        )
    ).all()

    out: list[AttentionOrderRow] = []
    for order, email_encrypted in rows:
        waiting_since = order.updated_at
        out.append(
            AttentionOrderRow(
                order_id=order.id,
                # `orders` has no human-facing number of its own — the
                # payment reference is what finance and the buyer both
                # quote (services/orders.py's pending queue does the
                # same), and an order too young to have one shows its id.
                order_number=order.payment_reference or str(order.id)[:8],
                status=order.status,
                currency=order.currency,
                grand_total=float(order.grand_total),
                buyer_email=_buyer_email(crypto, email_encrypted),
                waiting_since=waiting_since,
                hours_waiting=max(0, int((now - waiting_since).total_seconds() // 3600)),
            )
        )
    return total, out


UNREADABLE_EMAIL = "(unreadable — key rotated)"


def _buyer_email(crypto: CryptoBox, email_encrypted: bytes | None) -> str | None:
    """Masked, and never allowed to break the dashboard.

    A decrypt failure returns an explicit marker rather than None, and
    the distinction is the point: None means "no address on file", the
    marker means "there is one and this deployment can no longer read
    it" (docs/STATUS.md §10 — every pending order in the dev database is
    in that state). `services/orders.py` already makes the same
    distinction on the finance queue; showing "unknown" for both would
    quietly turn a key-rotation incident into what looks like missing
    data."""
    if email_encrypted is None:
        return None
    try:
        return _mask_email(crypto.decrypt(email_encrypted))
    except Exception:
        return UNREADABLE_EMAIL


async def _ungraded_submissions(
    session: AsyncSession, *, tenant_id: uuid.UUID, now: datetime
) -> list[AttentionSubmissionRow]:
    stmt = (
        select(AssignmentSubmission, Lesson.title, Course.title)
        .join(Enrolment, Enrolment.id == AssignmentSubmission.enrolment_id)
        .join(Course, Course.id == Enrolment.course_id)
        .join(Module, Module.course_id == Course.id)
        .join(Lesson, Lesson.module_id == Module.id)
        .where(
            AssignmentSubmission.tenant_id == tenant_id,
            AssignmentSubmission.approved_at.is_(None),
            AssignmentSubmission.rejected_reason.is_(None),
        )
        .order_by(AssignmentSubmission.submitted_at)
        .limit(ATTENTION_LIMIT)
    )
    out: list[AttentionSubmissionRow] = []
    seen: set[uuid.UUID] = set()
    for submission, lesson_title, course_title in (await session.execute(stmt)).all():
        if submission.id in seen:
            continue
        seen.add(submission.id)
        out.append(
            AttentionSubmissionRow(
                submission_id=submission.id,
                enrolment_id=submission.enrolment_id,
                assignment_title=lesson_title,
                course_title=course_title,
                submitted_at=submission.submitted_at,
                hours_waiting=max(0, int((now - submission.submitted_at).total_seconds() // 3600)),
            )
        )
    return out


async def _failed_transcodes(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[AttentionTranscodeRow]:
    """`transcode_jobs` and `video_assets` carry no tenant_id — they hang
    off a lesson, and a lesson belongs to a course, which reaches a
    tenant only through `course_tenant_assignments`. Hence the join
    chain; an unattached asset (uploaded, never wired to a lesson)
    belongs to no tenant and correctly appears for none."""
    stmt = (
        select(TranscodeJob, VideoAsset.id, Lesson.title, Course.title)
        .join(VideoAsset, VideoAsset.transcode_job_id == TranscodeJob.id)
        .join(Lesson, Lesson.video_asset_id == VideoAsset.id)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Course.id.in_(_tenant_courses(tenant_id)),
            TranscodeJob.state == "failed",
        )
        .order_by(TranscodeJob.finished_at.desc().nullslast())
        .limit(ATTENTION_LIMIT)
    )
    return [
        AttentionTranscodeRow(
            transcode_job_id=job.id,
            video_asset_id=asset_id,
            lesson_title=lesson_title,
            course_title=course_title,
            error=job.error,
            failed_at=job.finished_at,
        )
        for job, asset_id, lesson_title, course_title in (await session.execute(stmt)).all()
    ]


async def _at_risk(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    now: datetime,
    course_id: uuid.UUID | None = None,
    limit: int | None = ATTENTION_LIMIT,
) -> tuple[int, list[AtRiskLearnerRow]]:
    stmt = (
        select(Enrolment, Course.id, Course.title, User.email_encrypted)
        .join(Course, Course.id == Enrolment.course_id)
        .join(User, User.id == Enrolment.user_id)
        .where(Enrolment.tenant_id == tenant_id, Enrolment.completed_at.is_(None))
    )
    if course_id is not None:
        stmt = stmt.where(Enrolment.course_id == course_id)
    rows = (await session.execute(stmt)).all()
    if not rows:
        return 0, []

    enrolment_ids = [row[0].id for row in rows]
    activity = await _activity_by_enrolment(session, enrolment_ids=enrolment_ids)
    lesson_totals: dict[uuid.UUID, int] = {}

    at_risk: list[AtRiskLearnerRow] = []
    for enrolment, course_uuid, course_title, _email in rows:
        if course_uuid not in lesson_totals:
            lesson_totals[course_uuid] = await _lesson_total(session, course_id=course_uuid)
        total = lesson_totals[course_uuid]
        completed, last_active = activity.get(enrolment.id, (0, None))
        progress = round(completed / total * 100) if total else 0
        if not _is_at_risk(
            enrolment, progress_percent=progress, last_active_at=last_active, now=now
        ):
            continue
        reference = last_active or enrolment.started_at or enrolment.created_at
        at_risk.append(
            AtRiskLearnerRow(
                enrolment_id=enrolment.id,
                course_id=course_uuid,
                course_title=course_title,
                # Not the email, not even masked: an enrolment reference
                # is enough to open the learner in the course screens
                # that DO carry the visibility gate.
                learner_reference=str(enrolment.id)[:8],
                progress_percent=progress,
                last_active_at=last_active,
                days_inactive=max(0, (now - reference).days),
            )
        )

    at_risk.sort(key=lambda r: r.days_inactive, reverse=True)
    total_at_risk = len(at_risk)
    return total_at_risk, at_risk[:limit] if limit is not None else at_risk


async def get_overview(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID
) -> OverviewResponse:
    now = datetime.now(UTC)
    month_start = _month_start(now)
    period = analytics_service.Period(preset=None, start=month_start, end=now)

    # actual_revenue returns (net, received, refunded); the dashboard
    # headline is net — money actually kept this month, refunds already
    # deducted, which is the figure the revenue screen leads with too.
    revenue_mtd, _received, _refunded = await analytics_service.actual_revenue(
        session, tenant_id=tenant_id, period=period
    )

    active_learners = int(
        (
            await session.execute(
                select(func.count(func.distinct(Enrolment.user_id))).where(
                    Enrolment.tenant_id == tenant_id,
                    Enrolment.started_at.is_not(None),
                    Enrolment.completed_at.is_(None),
                )
            )
        ).scalar_one()
    )

    completions = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Enrolment)
                .where(
                    Enrolment.tenant_id == tenant_id,
                    Enrolment.completed_at >= month_start,
                )
            )
        ).scalar_one()
    )

    certificates = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Certificate)
                .where(
                    Certificate.tenant_id == tenant_id,
                    Certificate.issued_at >= month_start,
                    Certificate.status == "valid",
                )
            )
        ).scalar_one()
    )

    upcoming = int(
        (
            await session.execute(
                select(func.count())
                .select_from(WorkshopSession)
                .where(
                    WorkshopSession.tenant_id == tenant_id,
                    WorkshopSession.status == "scheduled",
                    WorkshopSession.starts_at >= now,
                    WorkshopSession.starts_at < now + timedelta(days=30),
                )
            )
        ).scalar_one()
    )

    pending_count, payment_rows = await _payment_approvals(
        session, crypto, tenant_id=tenant_id, now=now
    )
    at_risk_total, at_risk_rows = await _at_risk(session, tenant_id=tenant_id, now=now)

    return OverviewResponse(
        generated_at=now,
        month_start=month_start,
        kpis=OverviewKpis(
            revenue_mtd=revenue_mtd,
            active_learners=active_learners,
            pending_approvals=pending_count,
            completions_this_month=completions,
            certificates_issued_this_month=certificates,
            upcoming_sessions=upcoming,
            at_risk_learners=at_risk_total,
        ),
        payment_approvals=payment_rows,
        ungraded_submissions=await _ungraded_submissions(session, tenant_id=tenant_id, now=now),
        failed_transcodes=await _failed_transcodes(session, tenant_id=tenant_id),
        at_risk=at_risk_rows,
    )


async def get_course_summaries(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> CourseSummaryResponse:
    now = datetime.now(UTC)
    courses = (
        await session.execute(
            select(Course.id, Course.title, Course.state)
            .where(Course.id.in_(_tenant_courses(tenant_id)))
            .order_by(Course.title)
        )
    ).all()

    counts = {
        row[0]: (int(row[1]), int(row[2]))
        for row in (
            await session.execute(
                select(
                    Enrolment.course_id,
                    func.count(),
                    func.count().filter(Enrolment.completed_at.is_not(None)),
                )
                .where(Enrolment.tenant_id == tenant_id)
                .group_by(Enrolment.course_id)
            )
        ).all()
    }

    _, at_risk_rows = await _at_risk(session, tenant_id=tenant_id, now=now, limit=None)
    at_risk_by_course: dict[uuid.UUID, int] = {}
    for row in at_risk_rows:
        at_risk_by_course[row.course_id] = at_risk_by_course.get(row.course_id, 0) + 1

    return CourseSummaryResponse(
        generated_at=now,
        courses=[
            CourseSummaryRow(
                course_id=course_id,
                title=title,
                state=state,
                enrolled=counts.get(course_id, (0, 0))[0],
                completed=counts.get(course_id, (0, 0))[1],
                completion_rate=_rate(
                    counts.get(course_id, (0, 0))[1], counts.get(course_id, (0, 0))[0]
                ),
                at_risk=at_risk_by_course.get(course_id, 0),
            )
            for course_id, title, state in courses
        ],
    )


def _rate(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


async def get_course_analytics(
    session: AsyncSession, *, tenant_id: uuid.UUID, course_id: uuid.UUID
) -> CourseAnalyticsResponse | None:
    now = datetime.now(UTC)
    course = (
        await session.execute(
            select(Course).where(Course.id == course_id, Course.id.in_(_tenant_courses(tenant_id)))
        )
    ).scalar_one_or_none()
    if course is None:
        return None

    enrolments = (
        (
            await session.execute(
                select(Enrolment).where(
                    Enrolment.tenant_id == tenant_id, Enrolment.course_id == course_id
                )
            )
        )
        .scalars()
        .all()
    )

    started = [e for e in enrolments if e.started_at is not None]
    completed = [e for e in enrolments if e.completed_at is not None]
    funnel = CourseFunnel(enrolled=len(enrolments), started=len(started), completed=len(completed))

    # Median, not mean: one learner who finishes a year late would drag a
    # mean into meaninglessness, and this number exists to answer "how
    # long does this course actually take?"
    durations = [
        (e.completed_at - (e.started_at or e.created_at)).total_seconds() / 86400
        for e in completed
        if e.completed_at is not None
    ]
    median_days = round(statistics.median(durations), 1) if durations else None

    lesson_rows = (
        await session.execute(
            select(Lesson.id, Lesson.title, Lesson.position, Module.title, Module.position)
            .join(Module, Module.id == Lesson.module_id)
            .where(Module.course_id == course_id)
            .order_by(Module.position, Lesson.position)
        )
    ).all()

    enrolment_ids = [e.id for e in enrolments]
    per_lesson: dict[uuid.UUID, tuple[int, int]] = {}
    if enrolment_ids:
        per_lesson = {
            row[0]: (int(row[1]), int(row[2]))
            for row in (
                await session.execute(
                    select(
                        LessonCompletion.lesson_id,
                        func.count(),
                        func.count().filter(LessonCompletion.state == "completed"),
                    )
                    .where(LessonCompletion.enrolment_id.in_(enrolment_ids))
                    .group_by(LessonCompletion.lesson_id)
                )
            ).all()
        }

    dropoff = [
        LessonDropoffRow(
            lesson_id=lesson_id,
            title=title,
            position=position,
            module_title=module_title,
            reached=per_lesson.get(lesson_id, (0, 0))[0],
            completed=per_lesson.get(lesson_id, (0, 0))[1],
            completion_rate=_rate(
                per_lesson.get(lesson_id, (0, 0))[1], per_lesson.get(lesson_id, (0, 0))[0]
            ),
        )
        for lesson_id, title, position, module_title, _mp in lesson_rows
    ]

    quiz_scores = await _quiz_scores(session, course_id=course_id, enrolment_ids=enrolment_ids)
    _, at_risk_rows = await _at_risk(
        session, tenant_id=tenant_id, now=now, course_id=course_id, limit=None
    )

    return CourseAnalyticsResponse(
        course_id=course.id,
        course_title=course.title,
        generated_at=now,
        funnel=funnel,
        completion_rate=_rate(len(completed), len(enrolments)),
        median_days_to_complete=median_days,
        lesson_dropoff=dropoff,
        quiz_scores=quiz_scores,
        at_risk=at_risk_rows,
    )


async def _quiz_scores(
    session: AsyncSession, *, course_id: uuid.UUID, enrolment_ids: list[uuid.UUID]
) -> list[QuizScoreRow]:
    # The FK points lesson -> quiz (`Lesson.quiz_id`), not quiz -> lesson:
    # a quiz is an activity a lesson *is*, so the lesson owns the link.
    quizzes = (
        await session.execute(
            select(Quiz.id, Lesson.title)
            .join(Lesson, Lesson.quiz_id == Quiz.id)
            .join(Module, Module.id == Lesson.module_id)
            .where(Module.course_id == course_id)
            .order_by(Module.position, Lesson.position)
        )
    ).all()
    if not quizzes or not enrolment_ids:
        return [
            QuizScoreRow(
                quiz_id=quiz_id,
                lesson_title=title,
                attempts=0,
                average_score=None,
                pass_rate=None,
                score_buckets=[0, 0, 0, 0, 0],
            )
            for quiz_id, title in quizzes
        ]

    out: list[QuizScoreRow] = []
    for quiz_id, title in quizzes:
        rows = (
            await session.execute(
                select(QuizAttempt.score, QuizAttempt.passed).where(
                    QuizAttempt.quiz_id == quiz_id,
                    QuizAttempt.enrolment_id.in_(enrolment_ids),
                    QuizAttempt.submitted_at.is_not(None),
                    QuizAttempt.invalidated_at.is_(None),
                )
            )
        ).all()
        scores = [float(score) for score, _ in rows if score is not None]
        passes = [bool(passed) for _, passed in rows if passed is not None]
        buckets = [0, 0, 0, 0, 0]
        for score in scores:
            # 100 belongs in the top bucket, not a sixth one.
            buckets[min(4, int(score // 20))] += 1
        out.append(
            QuizScoreRow(
                quiz_id=quiz_id,
                lesson_title=title,
                attempts=len(rows),
                average_score=round(sum(scores) / len(scores), 1) if scores else None,
                pass_rate=_rate(sum(passes), len(passes)) if passes else None,
                score_buckets=buckets,
            )
        )
    return out


__all__ = ["get_course_analytics", "get_course_summaries", "get_overview"]
