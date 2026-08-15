"""Assignments (02 §7.7, REQ-BYPASS-08).

The virus scan itself happens at the router layer, before storage is ever
touched (the same fail-closed sequence already established for payment
proofs and video sources) — by the time `submit()` is called, the file is
already known clean, which is what `scanned_at`/`scan_result` record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.assessment import Assignment, AssignmentSubmission
from src.models.audit import AuditAction
from src.models.learning import Enrolment
from src.models.user import User
from src.services import audit


@dataclass(frozen=True, slots=True)
class PendingSubmissionRow:
    submission_id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str
    learner_email: str
    version: int
    submitted_at: datetime


async def latest_submission(
    session: AsyncSession, *, enrolment_id: uuid.UUID, assignment_id: uuid.UUID
) -> AssignmentSubmission | None:
    stmt = (
        select(AssignmentSubmission)
        .where(
            AssignmentSubmission.enrolment_id == enrolment_id,
            AssignmentSubmission.assignment_id == assignment_id,
        )
        .order_by(AssignmentSubmission.version.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def submit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    enrolment_id: uuid.UUID,
    assignment_id: uuid.UUID,
    object_key: str,
) -> AssignmentSubmission:
    assignment = await session.get(Assignment, assignment_id)
    if assignment is None:
        raise NotFound("No such assignment.")

    previous = await latest_submission(
        session, enrolment_id=enrolment_id, assignment_id=assignment_id
    )
    version = (previous.version + 1) if previous else 1

    submission = AssignmentSubmission(
        id=uuid7(),
        tenant_id=tenant_id,
        enrolment_id=enrolment_id,
        assignment_id=assignment_id,
        object_key=object_key,
        scanned_at=datetime.now(UTC),
        scan_result="clean",
        version=version,
    )
    session.add(submission)
    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.ASSIGNMENT_SUBMITTED,
        actor_user_id=user_id,
        entity_type="assignment_submission",
        entity_id=submission.id,
        after={"version": version},
    )
    await session.flush()
    return submission


async def review(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    submission_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    approve: bool,
    rejected_reason: str | None = None,
) -> AssignmentSubmission:
    submission = await session.get(AssignmentSubmission, submission_id)
    if submission is None or submission.tenant_id != tenant_id:
        raise NotFound("No such submission.")
    if submission.approved_at is not None:
        raise AppError("This submission has already been approved.")
    if not approve and not rejected_reason:
        raise AppError("A reason is required to reject a submission.")

    submission.reviewed_by_user_id = reviewer_user_id
    if approve:
        submission.approved_at = datetime.now(UTC)
        submission.rejected_reason = None
    else:
        submission.rejected_reason = rejected_reason

    await audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.ASSIGNMENT_REVIEWED,
        actor_user_id=reviewer_user_id,
        entity_type="assignment_submission",
        entity_id=submission.id,
        after={"approved": approve, "rejected_reason": rejected_reason},
    )
    await session.flush()
    return submission


async def list_pending_submissions(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID
) -> list[PendingSubmissionRow]:
    """Submissions never yet reviewed (neither approved nor rejected) —
    the discovery half of `review()`. A rejected submission drops off this
    queue: the expected next step is the learner resubmitting a new
    `version`, which creates a fresh pending row, not re-reviewing the old
    one indefinitely."""
    stmt = (
        select(AssignmentSubmission, Assignment, User)
        .join(Assignment, Assignment.id == AssignmentSubmission.assignment_id)
        .join(Enrolment, Enrolment.id == AssignmentSubmission.enrolment_id)
        .join(User, User.id == Enrolment.user_id)
        .where(
            AssignmentSubmission.tenant_id == tenant_id,
            AssignmentSubmission.approved_at.is_(None),
            AssignmentSubmission.rejected_reason.is_(None),
        )
        .order_by(AssignmentSubmission.submitted_at)
    )
    rows = (await session.execute(stmt)).all()
    return [
        PendingSubmissionRow(
            submission_id=submission.id,
            assignment_id=assignment.id,
            assignment_title=assignment.title,
            learner_email=crypto.decrypt(user.email_encrypted),
            version=submission.version,
            submitted_at=submission.submitted_at,
        )
        for submission, assignment, user in rows
    ]


async def list_assignments(session: AsyncSession) -> list[Assignment]:
    """Ordered by title — same global-content shape as
    `courses_service.list_courses`, no tenant filter."""
    stmt = select(Assignment).order_by(Assignment.title)
    return list((await session.execute(stmt)).scalars().all())


async def get_assignment(session: AsyncSession, *, assignment_id: uuid.UUID) -> Assignment:
    assignment = await session.get(Assignment, assignment_id)
    if assignment is None:
        raise NotFound("No such assignment.")
    return assignment


__all__ = [
    "PendingSubmissionRow",
    "get_assignment",
    "latest_submission",
    "list_assignments",
    "list_pending_submissions",
    "review",
    "submit",
]
