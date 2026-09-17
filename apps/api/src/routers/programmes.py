"""Programmes (entry paths) — API endpoints (0047).

POST /learning-paths/{id}/steps — create a typed step on a path
POST /cohorts — create a cohort for an organisation
GET /cohorts — list cohorts for an organisation
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import AppError, Forbidden, NotFound
from src.models.organisation import OrganisationMember
from src.services import programmes

router = APIRouter(tags=["programmes"])


class CreateStepRequest:
    """Request to create a typed step on a learning path."""

    def __init__(self, **data: Any):
        self.kind = data.get("kind")
        self.title = data.get("title")
        self.position = data.get("position")
        self.phase_label = data.get("phase_label")
        self.optional = data.get("optional", False)
        self.course_id = data.get("course_id")
        self.workshop_id = data.get("workshop_id")
        self.assessment_template_id = data.get("assessment_template_id")
        self.evaluation_role = data.get("evaluation_role")
        self.completion_rules = data.get("completion_rules", {})


class CreateCohortRequest:
    """Request to create a cohort."""

    def __init__(self, **data: Any):
        self.learning_path_id = data.get("learning_path_id")
        self.course_id = data.get("course_id")
        self.organisation_id = data.get("organisation_id")
        self.title = data.get("title")
        self.starts_at = data.get("starts_at")
        self.ends_at = data.get("ends_at")
        self.capacity = data.get("capacity")
        self.lead_facilitator_id = data.get("lead_facilitator_id")
        self.participants = data.get("participants", [])


class StepResponse:
    """Response with created step details."""

    def __init__(self, step: Any):
        self.id = str(step.id)
        self.learning_path_id = str(step.learning_path_id)
        self.kind = step.kind
        self.title = step.title
        self.position = step.position
        self.phase_label = step.phase_label
        self.optional = step.optional
        self.course_id = str(step.course_id) if step.course_id else None
        self.workshop_id = str(step.workshop_id) if step.workshop_id else None
        self.assessment_template_id = (
            str(step.assessment_template_id) if step.assessment_template_id else None
        )
        self.evaluation_role = step.evaluation_role
        self.completion_rules = step.completion_rules


class CohortResponse:
    """Response with created cohort details."""

    def __init__(self, cohort: Any):
        self.id = str(cohort.id)
        self.tenant_id = str(cohort.tenant_id)
        self.learning_path_id = str(cohort.learning_path_id) if cohort.learning_path_id else None
        self.course_id = str(cohort.course_id) if cohort.course_id else None
        self.organisation_id = str(cohort.organisation_id) if cohort.organisation_id else None
        self.title = cohort.title
        self.starts_at = cohort.starts_at.isoformat() if cohort.starts_at else None
        self.ends_at = cohort.ends_at.isoformat() if cohort.ends_at else None
        self.capacity = cohort.capacity
        self.lead_facilitator_id = (
            str(cohort.lead_facilitator_id) if cohort.lead_facilitator_id else None
        )
        self.status = cohort.status
        self.created_at = cohort.created_at.isoformat()


@router.post(
    "/learning-paths/{learning_path_id}/steps",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a typed step on a learning path",
)
async def create_step(
    learning_path_id: uuid.UUID,
    body: dict[str, Any],
    principal: PrincipalDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Create a typed step (course, workshop, assessment, one_on_one, document)
    on a learning path.

    Requires course:edit permission.
    """
    principal.require("course:edit")
    kind = body.get("kind")
    title = body.get("title")
    position = body.get("position")
    if not isinstance(kind, str) or not kind:
        raise HTTPException(status_code=400, detail="kind is required")
    if not isinstance(title, str) or not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not isinstance(position, int):
        raise HTTPException(status_code=400, detail="position is required")
    try:
        step = await programmes.create_step(
            session,
            tenant_id=principal.tenant_id,
            learning_path_id=learning_path_id,
            kind=kind,
            title=title,
            position=position,
            phase_label=body.get("phase_label"),
            optional=body.get("optional", False),
            course_id=body.get("course_id"),
            workshop_id=body.get("workshop_id"),
            assessment_template_id=body.get("assessment_template_id"),
            evaluation_role=body.get("evaluation_role"),
            completion_rules=body.get("completion_rules"),
        )
        await session.commit()
        return StepResponse(step).__dict__
    except (NotFound, AppError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/learning-paths/{learning_path_id}/steps",
    response_model=list[dict[str, Any]],
    summary="List a learning path's typed steps",
)
async def list_steps(
    learning_path_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> list[dict[str, Any]]:
    """List a learning path's typed steps in position order.

    Requires course:edit — the same permission required to add a step,
    since this is the authoring view, not a learner-facing listing.
    """
    principal.require("course:edit")
    try:
        steps = await programmes.list_steps(
            session, tenant_id=principal.tenant_id, learning_path_id=learning_path_id
        )
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [StepResponse(step).__dict__ for step in steps]


@router.post(
    "/cohorts",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a cohort (programme run)",
)
async def create_cohort(
    body: dict[str, Any],
    principal: PrincipalDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Create a cohort (scheduled run of a learning path or course) for
    an organisation with participants.

    Pre-creates CohortStep rows for every path step and adds participants
    as CohortMember rows.

    Requires cohort:run permission.
    """
    principal.require("cohort:run")
    title = body.get("title")
    if not isinstance(title, str) or not title:
        raise HTTPException(status_code=400, detail="title is required")
    try:
        cohort = await programmes.create_cohort(
            session,
            tenant_id=principal.tenant_id,
            learning_path_id=body.get("learning_path_id"),
            course_id=body.get("course_id"),
            organisation_id=body.get("organisation_id"),
            title=title,
            starts_at=body.get("starts_at"),
            ends_at=body.get("ends_at"),
            capacity=body.get("capacity"),
            lead_facilitator_id=body.get("lead_facilitator_id"),
            participants=body.get("participants"),
        )
        await session.commit()
        return CohortResponse(cohort).__dict__
    except (NotFound, AppError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/cohorts",
    response_model=list[dict[str, Any]],
    summary="List cohorts",
)
async def list_cohorts(
    principal: PrincipalDep,
    session: SessionDep,
    organisation_id: uuid.UUID | None = Query(None),
    learning_path_id: uuid.UUID | None = Query(None),
) -> list[dict[str, Any]]:
    """List cohorts for the authenticated tenant, optionally filtered by
    organisation or learning path.

    Requires cohort:run (sees every cohort in the tenant), or admin
    membership of the specific organisation_id filtered for (sees only
    that organisation's cohorts) — "org:admin" was never a real
    permission code; the codebase's actual org-admin check is
    OrganisationMember.relationship == "admin" on the org in question,
    same pattern used for the assessment-platform instances list.
    """
    if "cohort:run" not in principal.permissions:
        if organisation_id is None:
            raise Forbidden("You do not have access to this resource.")
        is_org_admin = (
            await session.execute(
                select(OrganisationMember).where(
                    OrganisationMember.tenant_id == principal.tenant_id,
                    OrganisationMember.organisation_id == organisation_id,
                    OrganisationMember.user_id == principal.user_id,
                    OrganisationMember.relationship == "admin",
                )
            )
        ).scalar_one_or_none()
        if is_org_admin is None:
            raise Forbidden("You do not have access to this resource.")
    cohorts = await programmes.list_cohorts(
        session,
        tenant_id=principal.tenant_id,
        organisation_id=organisation_id,
        learning_path_id=learning_path_id,
    )
    return [CohortResponse(cohort).__dict__ for cohort in cohorts]
