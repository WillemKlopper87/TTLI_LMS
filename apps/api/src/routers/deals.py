"""Deals, tasks, notes (02 §10, REQ-CRM-01/02) — `deal:manage`-gated
throughout. Sales/CRM data, not a learner- or organisation-facing
surface, so unlike booking a workshop session there is no self-service
half to this router.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from src.core.deps import CryptoDep, PrincipalDep, SessionDep
from src.core.errors import NotFound
from src.schemas.crm import (
    ActivityResponse,
    CreateDealRequest,
    CreateNoteRequest,
    CreateTaskRequest,
    DealDetailResponse,
    DealResponse,
    DealsPage,
    NoteResponse,
    TaskResponse,
    UpdateDealStageRequest,
)
from src.services import deals as deals_service

router = APIRouter(tags=["crm"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


def _deal_response(row: deals_service.DealRow) -> DealResponse:
    return DealResponse(
        id=str(row.id),
        contact_email=row.contact_email,
        title=row.title,
        stage=row.stage,
        amount=row.amount,
        currency=row.currency,
        created_at=row.created_at,
    )


@router.post("/deals", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def create_deal(
    body: CreateDealRequest, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> DealResponse:
    principal.require("deal:manage")
    deal = await deals_service.create_deal(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        email=body.email,
        title=body.title,
        amount=body.amount,
        currency=body.currency,
        source=body.source,
        campaign=body.campaign,
        actor_user_id=principal.user_id,
    )
    detail = await deals_service.get_deal_detail(
        session, crypto, tenant_id=principal.tenant_id, deal_id=deal.id
    )
    return _deal_response(detail.deal)


@router.get("/deals", response_model=DealsPage)
async def list_deals(
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DealsPage:
    principal.require("deal:manage")
    rows, total = await deals_service.list_deals(
        session, crypto, tenant_id=principal.tenant_id, limit=limit, offset=offset
    )
    return DealsPage(
        items=[_deal_response(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/deals/{deal_id}", response_model=DealDetailResponse)
async def get_deal(
    deal_id: str, principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> DealDetailResponse:
    principal.require("deal:manage")
    detail = await deals_service.get_deal_detail(
        session, crypto, tenant_id=principal.tenant_id, deal_id=_parse_uuid(deal_id)
    )
    return DealDetailResponse(
        deal=_deal_response(detail.deal),
        tasks=[
            TaskResponse(id=str(t.id), title=t.title, due_at=t.due_at, completed_at=t.completed_at)
            for t in detail.tasks
        ],
        notes=[
            NoteResponse(
                id=str(n.id), body=n.body, author_email=n.author_email, created_at=n.created_at
            )
            for n in detail.notes
        ],
        activities=[
            ActivityResponse(id=str(a.id), kind=a.kind, detail=a.detail, created_at=a.created_at)
            for a in detail.activities
        ],
    )


@router.patch("/deals/{deal_id}/stage", response_model=DealResponse)
async def update_deal_stage(
    deal_id: str,
    body: UpdateDealStageRequest,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> DealResponse:
    principal.require("deal:manage")
    await deals_service.set_stage(
        session,
        tenant_id=principal.tenant_id,
        deal_id=_parse_uuid(deal_id),
        stage=body.stage,
        actor_user_id=principal.user_id,
    )
    detail = await deals_service.get_deal_detail(
        session, crypto, tenant_id=principal.tenant_id, deal_id=_parse_uuid(deal_id)
    )
    return _deal_response(detail.deal)


@router.post(
    "/deals/{deal_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED
)
async def create_task(
    deal_id: str, body: CreateTaskRequest, principal: PrincipalDep, session: SessionDep
) -> TaskResponse:
    principal.require("deal:manage")
    task = await deals_service.create_task(
        session,
        tenant_id=principal.tenant_id,
        deal_id=_parse_uuid(deal_id),
        title=body.title,
        due_at=body.due_at,
        assigned_to_user_id=_parse_uuid(body.assigned_to_user_id)
        if body.assigned_to_user_id
        else None,
        actor_user_id=principal.user_id,
    )
    return TaskResponse(
        id=str(task.id), title=task.title, due_at=task.due_at, completed_at=task.completed_at
    )


@router.post("/tasks/{task_id}/complete", response_model=TaskResponse)
async def complete_task(task_id: str, principal: PrincipalDep, session: SessionDep) -> TaskResponse:
    principal.require("deal:manage")
    task = await deals_service.complete_task(
        session,
        tenant_id=principal.tenant_id,
        task_id=_parse_uuid(task_id),
        actor_user_id=principal.user_id,
    )
    return TaskResponse(
        id=str(task.id), title=task.title, due_at=task.due_at, completed_at=task.completed_at
    )


@router.post(
    "/deals/{deal_id}/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED
)
async def add_note(
    deal_id: str,
    body: CreateNoteRequest,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
) -> NoteResponse:
    principal.require("deal:manage")
    note = await deals_service.add_note(
        session,
        tenant_id=principal.tenant_id,
        deal_id=_parse_uuid(deal_id),
        body=body.body,
        author_user_id=principal.user_id,
    )
    detail = await deals_service.get_deal_detail(
        session, crypto, tenant_id=principal.tenant_id, deal_id=_parse_uuid(deal_id)
    )
    author_email = next(n.author_email for n in detail.notes if n.id == note.id)
    return NoteResponse(
        id=str(note.id), body=note.body, author_email=author_email, created_at=note.created_at
    )


__all__ = ["router"]
