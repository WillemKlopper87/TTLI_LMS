"""The learner dashboard (`GET /learn/dashboard`).

One read that answers the whole signed-in landing screen: who you are,
every course you hold, how far into each you are, what to click next, and
what is coming up. Nothing here computes progress, completion state or
credential issuance for itself — it composes `services/enrolment.py`'s
`get_progress` (the same evaluation `GET /enrolments/{id}/progress`
serves) and `services/credentials.py`'s per-enrolment lookup, so the
dashboard and the course page can never disagree about the same learner.

`workshop_credits` is always `0`: credit-based booking is a documented
deferral (`0018`'s migration docstring, `services/workshops.py`), and
there is no table to count. It is reported rather than omitted because
the field is part of the agreed contract and a silently absent number
would read as a bug; a real credit ledger fills it in later without a
shape change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.models.assessment import Quiz, QuizAttempt
from src.models.user import User
from src.models.workshop import Booking, MeetingLink, Workshop, WorkshopSession
from src.services import credentials as credentials_service
from src.services import enrolment as enrolment_service
from src.services import identity

KIND_WORKSHOP = "workshop"
KIND_ASSESSMENT = "assessment"


@dataclass(frozen=True, slots=True)
class NextLesson:
    lesson_id: uuid.UUID
    title: str
    module_title: str
    position_label: str


@dataclass(frozen=True, slots=True)
class CertificateSummary:
    certificate_id: uuid.UUID
    certificate_number: str
    issued_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class EnrolmentCard:
    enrolment_id: uuid.UUID
    course_id: uuid.UUID
    course_title: str
    hero_colour: str | None
    status: str
    progress_percent: int
    lessons_total: int
    lessons_completed: int
    next_lesson: NextLesson | None
    started_at: datetime | None
    completed_at: datetime | None
    certificate: CertificateSummary | None


@dataclass(frozen=True, slots=True)
class Stats:
    in_progress: int
    completed: int
    certificates: int
    workshop_credits: int


@dataclass(frozen=True, slots=True)
class UpcomingItem:
    kind: str
    title: str
    subtitle: str
    starts_at: datetime | None = None
    join_url: str | None = None
    # P7: which MeetingProvider actually issued join_url — the "Join on
    # Teams" label used to be hardcoded regardless of provider (a real
    # bug found reviewing this pass), which read as a working Teams
    # link on a manually-run session.
    provider: str | None = None
    enrolment_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    quiz_id: uuid.UUID | None = None
    attempts_remaining: int | None = None


@dataclass(frozen=True, slots=True)
class Dashboard:
    first_name: str | None
    initials: str
    enrolments: list[EnrolmentCard]
    stats: Stats
    upcoming: list[UpcomingItem]


def _position_labels(
    rows: list[enrolment_service.LessonProgressRow],
) -> dict[uuid.UUID, str]:
    """lesson_id -> "Module 2, lesson 3".

    Counted from the row order, not from the stored `position` columns.
    `services/courses.py` numbers new modules and lessons from 0 while
    `0011`'s seed numbers from 1, so `position + 1` would read correctly
    for one and be off by one for the other. Ordinals within the already
    correctly ordered list are right for both, and stay right after any
    future renumbering."""
    module_ordinal: dict[uuid.UUID, int] = {}
    lessons_seen: dict[uuid.UUID, int] = {}
    labels: dict[uuid.UUID, str] = {}
    for row in rows:
        if row.module_id not in module_ordinal:
            module_ordinal[row.module_id] = len(module_ordinal) + 1
            lessons_seen[row.module_id] = 0
        lessons_seen[row.module_id] += 1
        labels[row.lesson_id] = (
            f"Module {module_ordinal[row.module_id]}, lesson {lessons_seen[row.module_id]}"
        )
    return labels


def _status(*, completed_at: datetime | None, started_at: datetime | None, completed: int) -> str:
    if completed_at is not None:
        return "completed"
    if started_at is not None or completed > 0:
        return "in_progress"
    return "not_started"


async def _attempts_remaining(session: AsyncSession, *, enrolment_id: uuid.UUID, quiz: Quiz) -> int:
    """The same arithmetic `services/quiz.py::start_attempt` enforces —
    invalidated attempts don't count against the limit there either, so
    they must not count here or the dashboard would under-report."""
    used = (
        await session.execute(
            select(func.count())
            .select_from(QuizAttempt)
            .where(
                QuizAttempt.enrolment_id == enrolment_id,
                QuizAttempt.quiz_id == quiz.id,
                QuizAttempt.invalidated_at.is_(None),
            )
        )
    ).scalar_one()
    return max(0, quiz.max_attempts - int(used))


async def _upcoming_workshops(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> list[UpcomingItem]:
    """The learner's own still-registered bookings for sessions that have
    not started yet. Waitlisted and cancelled bookings are deliberately
    absent — neither is something to turn up to."""
    stmt = (
        select(Booking, WorkshopSession, Workshop, MeetingLink)
        .join(WorkshopSession, WorkshopSession.id == Booking.session_id)
        .join(Workshop, Workshop.id == WorkshopSession.workshop_id)
        .outerjoin(MeetingLink, MeetingLink.session_id == WorkshopSession.id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.user_id == user_id,
            Booking.status == "registered",
            WorkshopSession.status == "scheduled",
            WorkshopSession.starts_at > now,
        )
        .order_by(WorkshopSession.starts_at)
    )
    items: list[UpcomingItem] = []
    for _booking, workshop_session, workshop, meeting_link in (
        await session.execute(stmt)
    ).tuples():
        items.append(
            UpcomingItem(
                kind=KIND_WORKSHOP,
                title=workshop.title,
                subtitle=workshop.description
                or workshop.session_type.replace("_", " ").capitalize(),
                starts_at=workshop_session.starts_at,
                join_url=meeting_link.join_url if meeting_link is not None else None,
                provider=meeting_link.provider if meeting_link is not None else None,
            )
        )
    return items


async def get_dashboard(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Dashboard:
    user = await session.get(User, user_id)
    who = (
        identity.display_identity(user, crypto)
        if user is not None
        else identity.DisplayIdentity(full_name=None, first_name=None, initials="?")
    )
    now = datetime.now(UTC)

    cards: list[EnrolmentCard] = []
    assessments: list[UpcomingItem] = []
    certificates = 0

    for row in await enrolment_service.list_own_enrolments(
        session, tenant_id=tenant_id, user_id=user_id
    ):
        progress = await enrolment_service.get_progress(
            session, crypto, tenant_id=tenant_id, user_id=user_id, enrolment_id=row.enrolment_id
        )
        lessons_completed = sum(1 for x in progress.lessons if x.state == "completed")
        by_id = {x.lesson_id: x for x in progress.lessons}
        labels = _position_labels(progress.lessons)
        next_row = by_id.get(progress.next_lesson_id) if progress.next_lesson_id else None
        certificate, _badge = await credentials_service.get_for_enrolment(
            session, tenant_id=tenant_id, enrolment_id=row.enrolment_id, user_id=user_id
        )
        if certificate is not None:
            certificates += 1

        cards.append(
            EnrolmentCard(
                enrolment_id=row.enrolment_id,
                course_id=progress.course.id,
                course_title=progress.course.title,
                hero_colour=progress.course.hero_colour,
                status=_status(
                    completed_at=progress.enrolment.completed_at,
                    started_at=progress.enrolment.started_at,
                    completed=lessons_completed,
                ),
                progress_percent=progress.progress_percent,
                lessons_total=len(progress.lessons),
                lessons_completed=lessons_completed,
                next_lesson=NextLesson(
                    lesson_id=next_row.lesson_id,
                    title=next_row.title,
                    module_title=next_row.module_title,
                    position_label=labels[next_row.lesson_id],
                )
                if next_row is not None
                else None,
                started_at=progress.enrolment.started_at,
                completed_at=progress.enrolment.completed_at,
                certificate=CertificateSummary(
                    certificate_id=certificate.id,
                    certificate_number=certificate.certificate_number,
                    issued_at=certificate.issued_at,
                    status=certificate.status,
                )
                if certificate is not None
                else None,
            )
        )

        for lesson_row in progress.lessons:
            if lesson_row.quiz_id is None or lesson_row.state not in ("available", "in_progress"):
                continue
            quiz = await session.get(Quiz, lesson_row.quiz_id)
            if quiz is None:  # pragma: no cover - FK guarantees this
                continue
            assessments.append(
                UpcomingItem(
                    kind=KIND_ASSESSMENT,
                    title=quiz.title,
                    subtitle=progress.course.title,
                    enrolment_id=row.enrolment_id,
                    lesson_id=lesson_row.lesson_id,
                    quiz_id=quiz.id,
                    attempts_remaining=await _attempts_remaining(
                        session, enrolment_id=row.enrolment_id, quiz=quiz
                    ),
                )
            )

    upcoming = (
        await _upcoming_workshops(session, tenant_id=tenant_id, user_id=user_id, now=now)
        + assessments
    )
    return Dashboard(
        first_name=who.first_name,
        initials=who.initials,
        enrolments=cards,
        stats=Stats(
            in_progress=sum(1 for c in cards if c.status == "in_progress"),
            completed=sum(1 for c in cards if c.status == "completed"),
            certificates=certificates,
            workshop_credits=0,
        ),
        upcoming=upcoming,
    )


__all__ = [
    "KIND_ASSESSMENT",
    "KIND_WORKSHOP",
    "CertificateSummary",
    "Dashboard",
    "EnrolmentCard",
    "NextLesson",
    "Stats",
    "UpcomingItem",
    "get_dashboard",
]
