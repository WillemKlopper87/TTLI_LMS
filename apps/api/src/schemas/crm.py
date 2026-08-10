from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from src.models.crm import DEAL_STAGE_VALUES


class CreateDealRequest(BaseModel):
    email: str
    title: str = Field(min_length=1, max_length=200)
    amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source: str | None = None
    campaign: str | None = None


class UpdateDealStageRequest(BaseModel):
    stage: str = Field(pattern="^(" + "|".join(DEAL_STAGE_VALUES) + ")$")


class DealResponse(BaseModel):
    id: str
    contact_email: str
    title: str
    stage: str
    amount: Decimal | None
    currency: str | None
    created_at: datetime


class DealsPage(BaseModel):
    items: list[DealResponse]
    total: int
    limit: int
    offset: int


class TaskResponse(BaseModel):
    id: str
    title: str
    due_at: datetime | None
    completed_at: datetime | None


class NoteResponse(BaseModel):
    id: str
    body: str
    author_email: str
    created_at: datetime


class ActivityResponse(BaseModel):
    id: str
    kind: str
    detail: dict[str, object]
    created_at: datetime


class DealDetailResponse(BaseModel):
    deal: DealResponse
    tasks: list[TaskResponse]
    notes: list[NoteResponse]
    activities: list[ActivityResponse]


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    assigned_to_user_id: str | None = None


class CreateNoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


__all__ = [
    "ActivityResponse",
    "CreateDealRequest",
    "CreateNoteRequest",
    "CreateTaskRequest",
    "DealDetailResponse",
    "DealResponse",
    "DealsPage",
    "NoteResponse",
    "TaskResponse",
    "UpdateDealStageRequest",
]
