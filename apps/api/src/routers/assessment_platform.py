"""Assessment platform endpoints: templates and instances (foundation slice).

Routes:
  POST   /assessment-platform/templates     Create template (assessment:author)
  GET    /assessment-platform/templates     List templates (assessment:author | assessment:analyse)
  POST   /assessment-platform/instances     Create instance (assessment:run)
  GET    /assessment-platform/instances     List instances (assessment:run | org membership)

The first slice exposing the foundation data model (template/instance create and list).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import Forbidden, NotFound
from src.services import assessment_template as assessment_service

router = APIRouter(prefix="/assessment-platform", tags=["assessment-platform"])


class TemplateCreateRequest(BaseModel):
    """Create a new assessment template."""

    slug: str
    title: str
    kind: str
    description: str | None = None
    response_mode: str = "identified"
    minimum_group_size: int = 5


class TemplateResponse(BaseModel):
    """Assessment template response."""

    id: str
    tenant_id: str
    slug: str
    title: str
    kind: str
    response_mode: str
    status: str
    version: int


class TemplatesPageResponse(BaseModel):
    """List of templates."""

    items: list[TemplateResponse]


class InstanceCreateRequest(BaseModel):
    """Create a new assessment instance."""

    template_id: str
    organisation_id: str
    title: str
    evaluation_role: str = "standalone"
    levels_enabled: bool = False


class InstanceResponse(BaseModel):
    """Assessment instance response."""

    id: str
    tenant_id: str
    template_id: str
    organisation_id: str
    title: str
    status: str
    evaluation_role: str


class InstancesPageResponse(BaseModel):
    """List of instances."""

    items: list[InstanceResponse]


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreateRequest, principal: PrincipalDep, session: SessionDep
) -> TemplateResponse:
    """Create a new assessment template in draft status.

    Requires assessment:author permission.
    """
    principal.require("assessment:author")
    template = await assessment_service.create_template(
        session,
        tenant_id=principal.tenant_id,
        slug=body.slug,
        title=body.title,
        kind=body.kind,
        description=body.description,
        response_mode=body.response_mode,
        minimum_group_size=body.minimum_group_size,
        created_by=principal.user_id,
    )
    return TemplateResponse(
        id=str(template.id),
        tenant_id=str(template.tenant_id),
        slug=template.slug,
        title=template.title,
        kind=template.kind,
        response_mode=template.response_mode,
        status=template.status,
        version=template.version,
    )


@router.get("/templates", response_model=TemplatesPageResponse)
async def list_templates(principal: PrincipalDep, session: SessionDep) -> TemplatesPageResponse:
    """List all assessment templates for the tenant.

    Requires assessment:author or assessment:analyse permission.
    """
    if not principal.permissions & {"assessment:author", "assessment:analyse"}:
        raise Forbidden("You do not have access to this resource.")
    rows = await assessment_service.list_templates(session, tenant_id=principal.tenant_id)
    return TemplatesPageResponse(
        items=[
            TemplateResponse(
                id=str(t.id),
                tenant_id=str(t.tenant_id),
                slug=t.slug,
                title=t.title,
                kind=t.kind,
                response_mode=t.response_mode,
                status=t.status,
                version=t.version,
            )
            for t, _ in rows
        ]
    )


@router.post("/instances", response_model=InstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_instance(
    body: InstanceCreateRequest, principal: PrincipalDep, session: SessionDep
) -> InstanceResponse:
    """Create a new assessment instance for an organisation.

    Starts in draft status. Admin must populate questions and set window before opening.
    Requires assessment:run permission.
    """
    principal.require("assessment:run")
    try:
        template_uuid = uuid.UUID(body.template_id)
        organisation_uuid = uuid.UUID(body.organisation_id)
    except ValueError as exc:
        raise NotFound("Invalid template or organisation ID.") from exc

    instance = await assessment_service.create_instance(
        session,
        tenant_id=principal.tenant_id,
        template_id=template_uuid,
        organisation_id=organisation_uuid,
        title=body.title,
        evaluation_role=body.evaluation_role,
        levels_enabled=body.levels_enabled,
        created_by=principal.user_id,
    )
    return InstanceResponse(
        id=str(instance.id),
        tenant_id=str(instance.tenant_id),
        template_id=str(instance.template_id),
        organisation_id=str(instance.organisation_id),
        title=instance.title,
        status=instance.status,
        evaluation_role=instance.evaluation_role,
    )


@router.get("/instances", response_model=InstancesPageResponse)
async def list_instances(principal: PrincipalDep, session: SessionDep) -> InstancesPageResponse:
    """List assessment instances accessible to the caller.

    Requires assessment:run permission or org membership.
    """
    principal.require("assessment:run")
    instances = await assessment_service.list_instances(session, tenant_id=principal.tenant_id)
    return InstancesPageResponse(
        items=[
            InstanceResponse(
                id=str(i.id),
                tenant_id=str(i.tenant_id),
                template_id=str(i.template_id),
                organisation_id=str(i.organisation_id),
                title=i.title,
                status=i.status,
                evaluation_role=i.evaluation_role,
            )
            for i in instances
        ]
    )


__all__ = ["router"]
