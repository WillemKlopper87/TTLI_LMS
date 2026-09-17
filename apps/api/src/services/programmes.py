"""Programmes (entry paths) — service operations (0047).

Core operations: creating typed steps on paths, creating cohorts for
organisations with participants, and listing cohorts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.models.course import Course, CourseTenantAssignment
from src.models.learning_path import LearningPath, LearningPathStep, LearningPathTenantAssignment
from src.models.organisation import Organisation
from src.models.programme import Cohort, CohortMember, CohortStep
from src.models.user import User

log = structlog.get_logger(__name__)


async def create_step(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    learning_path_id: uuid.UUID,
    kind: str,
    title: str,
    position: int,
    phase_label: str | None = None,
    optional: bool = False,
    course_id: uuid.UUID | None = None,
    workshop_id: uuid.UUID | None = None,
    assessment_template_id: uuid.UUID | None = None,
    evaluation_role: str | None = None,
    completion_rules: dict[str, Any] | None = None,
) -> LearningPathStep:
    """Create a typed step on a learning path.

    Args:
        session: Database session
        learning_path_id: Path to add the step to
        kind: Step kind (course, workshop, assessment, one_on_one, document)
        title: Step title
        position: Position in the path
        phase_label: Optional phase label (e.g. "Phase 1: Discovery")
        optional: Whether this step is optional (used for ESWS pick-lists)
        course_id: FK to courses (for course steps)
        workshop_id: FK to workshops (for workshop steps)
        assessment_template_id: FK to assessment_templates (for assessment steps)
        evaluation_role: 'pre', 'post', or None (for paired assessment steps)
        completion_rules: JSONB completion rules (course, workshop, etc.)

    Returns:
        The created LearningPathStep

    Raises:
        NotFound: If learning_path_id doesn't exist
        AppError: If kind/FK combination is invalid
    """
    # Verify the path exists AND is assigned to this tenant. LearningPath
    # rows are deliberately global (models/learning_path.py's own
    # docstring — same split as courses/CourseTenantAssignment); the join
    # through LearningPathTenantAssignment is what stops a caller in one
    # tenant from adding a step to a path they were never assigned.
    path = (
        await session.execute(
            select(LearningPath)
            .join(
                LearningPathTenantAssignment,
                LearningPathTenantAssignment.learning_path_id == LearningPath.id,
            )
            .where(
                LearningPath.id == learning_path_id,
                LearningPathTenantAssignment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not path:
        raise NotFound(f"Learning path {learning_path_id} not found")

    # Validate kind and FK
    if kind == "course" and not course_id:
        raise AppError("Course steps must specify course_id")
    if kind == "workshop" and not workshop_id:
        raise AppError("Workshop steps must specify workshop_id")
    if kind == "assessment" and not assessment_template_id:
        raise AppError("Assessment steps must specify assessment_template_id")
    # one_on_one and document steps have no required FK at creation time.
    if evaluation_role is not None and evaluation_role not in ("pre", "post"):
        raise AppError(f"Invalid evaluation_role {evaluation_role!r}; must be 'pre' or 'post'.")

    # Pre-check rather than letting a duplicate position hit the deferred
    # unique constraint at commit — that constraint is deferred so
    # reorder_path_courses' whole-permutation swap works, not so a single
    # new step's collision should surface as an unhandled 500.
    existing_position = (
        await session.execute(
            select(LearningPathStep.id).where(
                LearningPathStep.learning_path_id == learning_path_id,
                LearningPathStep.position == position,
            )
        )
    ).scalar_one_or_none()
    if existing_position is not None:
        raise AppError(f"Position {position} is already taken on this path.")

    step = LearningPathStep(
        learning_path_id=learning_path_id,
        kind=kind,
        title=title,
        position=position,
        phase_label=phase_label,
        optional=optional,
        course_id=course_id,
        workshop_id=workshop_id,
        assessment_template_id=assessment_template_id,
        evaluation_role=evaluation_role,
        completion_rules=completion_rules or {},
    )
    session.add(step)
    await session.flush()
    log.info(
        "step_created",
        step_id=str(step.id),
        learning_path_id=str(learning_path_id),
        kind=kind,
        position=position,
    )
    return step


async def list_steps(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    learning_path_id: uuid.UUID,
) -> list[LearningPathStep]:
    """List a learning path's typed steps in position order.

    Same tenant-visibility scoping as create_step — a path this tenant
    was never assigned to raises NotFound rather than an empty list, so
    "no steps yet" and "not your path" stay distinguishable.
    """
    path = (
        await session.execute(
            select(LearningPath)
            .join(
                LearningPathTenantAssignment,
                LearningPathTenantAssignment.learning_path_id == LearningPath.id,
            )
            .where(
                LearningPath.id == learning_path_id,
                LearningPathTenantAssignment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not path:
        raise NotFound(f"Learning path {learning_path_id} not found")

    result = await session.execute(
        select(LearningPathStep)
        .where(LearningPathStep.learning_path_id == learning_path_id)
        .order_by(LearningPathStep.position)
    )
    return list(result.scalars().all())


async def create_cohort(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    learning_path_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    organisation_id: uuid.UUID | None = None,
    title: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    capacity: int | None = None,
    lead_facilitator_id: uuid.UUID | None = None,
    participants: list[dict[str, Any]] | None = None,
) -> Cohort:
    """Create a cohort (programme run) for an organisation.

    A cohort run instantiates a learning path (or course) for an organisation
    with a set of participants. Pre-creates CohortStep rows for every path step
    at status='pending'.

    Args:
        session: Database session
        tenant_id: Tenant owning the cohort
        learning_path_id: Path to run (XOR with course_id)
        course_id: Course to run (XOR with learning_path_id)
        organisation_id: Organisation running the cohort
        title: Cohort title
        starts_at: Optional start date
        ends_at: Optional end date
        capacity: Optional capacity (seats consumed by participants)
        lead_facilitator_id: Optional lead facilitator
        participants: List of {'user_id': uuid, 'role': 'participant' | 'observer'} dicts

    Returns:
        The created Cohort

    Raises:
        NotFound: If learning_path_id, course_id, organisation_id, or
            lead_facilitator_id don't exist
        AppError: If neither learning_path_id nor course_id specified, or
            both specified
    """
    # Validate XOR on learning_path_id vs course_id
    if not learning_path_id and not course_id:
        raise AppError("Must specify either learning_path_id or course_id")
    if learning_path_id and course_id:
        raise AppError("Cannot specify both learning_path_id and course_id")

    # Verify path or course exists — scoped by tenant_id, not just by id.
    # session.get() alone would accept another tenant's row: a caller in
    # tenant A passing tenant B's learning_path_id/organisation_id/
    # lead_facilitator_id would otherwise create a cohort against data it
    # has no business touching (the same class of cross-tenant leak F1/F2
    # closed for tenant-domain caching elsewhere in this repo).
    if learning_path_id:
        path = (
            await session.execute(
                select(LearningPath)
                .join(
                    LearningPathTenantAssignment,
                    LearningPathTenantAssignment.learning_path_id == LearningPath.id,
                )
                .where(
                    LearningPath.id == learning_path_id,
                    LearningPathTenantAssignment.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if not path:
            raise NotFound(f"Learning path {learning_path_id} not found")
    else:
        # Same tenant-visibility scoping as the learning_path_id branch
        # above, mirrored through CourseTenantAssignment — a bare
        # session.get(Course, id) would accept another tenant's course.
        course = (
            await session.execute(
                select(Course)
                .join(
                    CourseTenantAssignment,
                    CourseTenantAssignment.course_id == Course.id,
                )
                .where(
                    Course.id == course_id,
                    CourseTenantAssignment.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if not course:
            raise NotFound(f"Course {course_id} not found")

    # Verify organisation and lead facilitator if provided
    if organisation_id:
        org = (
            await session.execute(
                select(Organisation).where(
                    Organisation.id == organisation_id,
                    Organisation.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if not org:
            raise NotFound(f"Organisation {organisation_id} not found")

    if lead_facilitator_id:
        facilitator = (
            await session.execute(
                select(User).where(
                    User.id == lead_facilitator_id,
                    User.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if not facilitator:
            raise NotFound(f"User {lead_facilitator_id} not found")

    # Create cohort
    cohort = Cohort(
        tenant_id=tenant_id,
        learning_path_id=learning_path_id,
        course_id=course_id,
        organisation_id=organisation_id,
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=capacity,
        lead_facilitator_id=lead_facilitator_id,
        status="planned",
    )
    session.add(cohort)
    await session.flush()

    # Pre-create cohort_steps for every path step (at status='pending')
    if learning_path_id:
        steps = (
            await session.execute(
                select(LearningPathStep)
                .where(LearningPathStep.learning_path_id == learning_path_id)
                .order_by(LearningPathStep.position)
            )
        ).scalars()

        for step in steps:
            cohort_step = CohortStep(
                cohort_id=cohort.id,
                step_id=step.id,
                status="pending",
            )
            session.add(cohort_step)

    await session.flush()

    # Add participants as cohort_members
    if participants:
        for participant in participants:
            user_id = participant.get("user_id")
            role = participant.get("role", "participant")
            if role not in ("participant", "observer"):
                raise AppError(f"Invalid participant role {role!r}.")

            user = (
                await session.execute(
                    select(User).where(User.id == user_id, User.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if not user:
                log.warning(
                    "participant_user_not_found",
                    user_id=str(user_id),
                    cohort_id=str(cohort.id),
                )
                continue

            member = CohortMember(
                tenant_id=tenant_id,
                cohort_id=cohort.id,
                user_id=user_id,
                role=role,
            )
            session.add(member)

    await session.flush()

    log.info(
        "cohort_created",
        cohort_id=str(cohort.id),
        tenant_id=str(tenant_id),
        learning_path_id=str(learning_path_id) if learning_path_id else None,
        organisation_id=str(organisation_id) if organisation_id else None,
        participant_count=len(participants) if participants else 0,
    )
    return cohort


async def list_cohorts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID | None = None,
    learning_path_id: uuid.UUID | None = None,
) -> list[Cohort]:
    """List cohorts for a tenant, optionally filtered by organisation or path.

    Args:
        session: Database session
        tenant_id: Tenant ID
        organisation_id: Optional organisation to filter by
        learning_path_id: Optional learning path to filter by

    Returns:
        List of Cohort rows
    """
    query = select(Cohort).where(Cohort.tenant_id == tenant_id)

    if organisation_id:
        query = query.where(Cohort.organisation_id == organisation_id)

    if learning_path_id:
        query = query.where(Cohort.learning_path_id == learning_path_id)

    result = await session.execute(query.order_by(Cohort.created_at.desc()))
    return list(result.scalars().all())
