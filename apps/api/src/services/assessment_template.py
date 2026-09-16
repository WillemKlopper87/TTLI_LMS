"""Assessment template and instance service: create, read, list operations.

The first slice of the assessment platform (§2026-09-11-assessment-platform-design.md):
foundation models and basic CRUD. Covers template creation/listing and instance
creation/listing, enough to exercise the data model and establish patterns for
the full API surface to follow.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.assessment_template import (
    AssessmentInstance,
    AssessmentTemplate,
    AssessmentTemplateQuestion,
)


async def create_template(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    slug: str,
    title: str,
    kind: str,
    description: str | None = None,
    response_mode: str = "identified",
    minimum_group_size: int = 5,
    rater_groups: list[dict[str, Any]] | None = None,
    vendor: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    created_by: uuid.UUID | None = None,
) -> AssessmentTemplate:
    """Create a new assessment template in draft status.

    Templates are versioned by (tenant_id, slug, version). Creating a template
    always starts at version 1; subsequent versions are added explicitly.
    """
    # Validate kind
    allowed_kinds = ("org_survey", "multi_rater", "individual", "external_instrument")
    if kind not in allowed_kinds:
        raise AppError(f"Invalid kind {kind!r}. Must be one of {allowed_kinds}.")

    # Validate response_mode
    if response_mode not in ("identified", "anonymous"):
        raise AppError(f"Invalid response_mode {response_mode!r}.")

    template = AssessmentTemplate(
        id=uuid7(),
        tenant_id=tenant_id,
        slug=slug,
        title=title,
        description=description,
        kind=kind,
        response_mode=response_mode,
        minimum_group_size=minimum_group_size,
        rater_groups=rater_groups or [],
        vendor=vendor,
        status="draft",
        sections=sections or [],
        created_by=created_by,
    )
    session.add(template)
    await session.flush()
    return template


async def get_template(
    session: AsyncSession, *, tenant_id: uuid.UUID, template_id: uuid.UUID
) -> AssessmentTemplate:
    """Retrieve a template by ID, checking tenant isolation."""
    stmt = select(AssessmentTemplate).where(
        and_(
            AssessmentTemplate.id == template_id,
            AssessmentTemplate.tenant_id == tenant_id,
        )
    )
    result = await session.scalar(stmt)
    if result is None:
        raise NotFound("No such assessment template.")
    return result


async def list_templates(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[tuple[AssessmentTemplate, int]]:
    """List all templates for a tenant with question count.

    Returns tuples of (template, question_count).
    """
    stmt = (
        select(AssessmentTemplate, func_count_questions())
        .where(AssessmentTemplate.tenant_id == tenant_id)
        .order_by(AssessmentTemplate.created_at.desc())
    )
    result = await session.execute(stmt)
    return result.all()


async def create_instance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    organisation_id: uuid.UUID,
    title: str,
    evaluation_role: str = "standalone",
    pair_id: uuid.UUID | None = None,
    levels_enabled: bool = False,
    opens_at: Any = None,
    closes_at: Any = None,
    created_by: uuid.UUID | None = None,
) -> AssessmentInstance:
    """Create an instance for an organisation, starting in draft status.

    Snapshot starts empty in draft and is populated by the admin before opening.
    """
    # Fetch template to get version
    template = await get_template(session, tenant_id=tenant_id, template_id=template_id)

    # Validate evaluation_role and pair_id coherence
    if evaluation_role not in ("standalone", "pre", "post"):
        raise AppError(f"Invalid evaluation_role {evaluation_role!r}.")

    if evaluation_role == "standalone" and pair_id is not None:
        raise AppError("Standalone instances cannot have a pair_id.")

    if evaluation_role in ("pre", "post") and pair_id is None:
        raise AppError(f"{evaluation_role} instances must have a pair_id.")

    instance = AssessmentInstance(
        id=uuid7(),
        tenant_id=tenant_id,
        template_id=template_id,
        template_version=template.version,
        organisation_id=organisation_id,
        title=title,
        status="draft",
        evaluation_role=evaluation_role,
        pair_id=pair_id,
        levels_enabled=levels_enabled,
        opens_at=opens_at,
        closes_at=closes_at,
        created_by=created_by,
    )
    session.add(instance)
    await session.flush()
    return instance


async def get_instance(
    session: AsyncSession, *, tenant_id: uuid.UUID, instance_id: uuid.UUID
) -> AssessmentInstance:
    """Retrieve an instance by ID, checking tenant isolation."""
    stmt = select(AssessmentInstance).where(
        and_(
            AssessmentInstance.id == instance_id,
            AssessmentInstance.tenant_id == tenant_id,
        )
    )
    result = await session.scalar(stmt)
    if result is None:
        raise NotFound("No such assessment instance.")
    return result


async def list_instances(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID | None = None,
) -> list[AssessmentInstance]:
    """List instances for a tenant, optionally filtered by organisation."""
    stmt = select(AssessmentInstance).where(
        AssessmentInstance.tenant_id == tenant_id,
    )
    if organisation_id is not None:
        stmt = stmt.where(AssessmentInstance.organisation_id == organisation_id)
    stmt = stmt.order_by(AssessmentInstance.created_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


def func_count_questions() -> Any:
    """Subquery to count questions for a template.

    Used by list_templates to avoid N+1 queries.
    """
    from sqlalchemy import func

    subq = select(func.count(AssessmentTemplateQuestion.id)).where(
        AssessmentTemplateQuestion.template_id == AssessmentTemplate.id
    )
    return subq.scalar_subquery()
