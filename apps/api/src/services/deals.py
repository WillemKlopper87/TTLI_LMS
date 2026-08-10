"""Deals, tasks, notes, activities (02 §10, REQ-CRM-01/02). Deal-centric:
every task and note hangs off a deal, and every mutation writes a real
`activities` row — a deal's own append-only history, not a derived view.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.contact import Contact
from src.models.crm import DEAL_STAGE_VALUES, Activity, Deal, Note, Task
from src.models.user import User
from src.services import leads as leads_service


class DealError(AppError):
    """A refusal in the CRM flow — an unknown stage, a task already
    completed, or a similar invalid state transition."""

    code = "DEAL_ERROR"


async def _log_activity(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    deal_id: uuid.UUID,
    kind: str,
    detail: dict[str, object],
    actor_user_id: uuid.UUID | None,
) -> None:
    session.add(
        Activity(
            id=uuid7(),
            tenant_id=tenant_id,
            deal_id=deal_id,
            kind=kind,
            detail=detail,
            actor_user_id=actor_user_id,
        )
    )


async def create_deal(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    email: str,
    title: str,
    amount: Decimal | None,
    currency: str | None,
    source: str | None,
    campaign: str | None,
    actor_user_id: uuid.UUID,
) -> Deal:
    capture = await leads_service.capture(
        session,
        crypto,
        tenant_id=tenant_id,
        email=email,
        first_name=None,
        last_name=None,
        source=source,
        profile={},
        utm={},
    )
    deal = Deal(
        id=uuid7(),
        tenant_id=tenant_id,
        contact_id=capture.contact_id,
        title=title,
        amount=amount,
        currency=currency,
        source=source,
        campaign=campaign,
    )
    session.add(deal)
    await session.flush()
    await _log_activity(
        session,
        tenant_id=tenant_id,
        deal_id=deal.id,
        kind="deal_created",
        detail={"title": title},
        actor_user_id=actor_user_id,
    )
    await session.flush()
    return deal


async def set_stage(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    deal_id: uuid.UUID,
    stage: str,
    actor_user_id: uuid.UUID,
) -> Deal:
    if stage not in DEAL_STAGE_VALUES:
        raise DealError(f"Unknown stage: {stage}")
    deal = await session.get(Deal, deal_id)
    if deal is None or deal.tenant_id != tenant_id:
        raise NotFound("No such deal.")
    previous = deal.stage
    if previous == stage:
        return deal
    deal.stage = stage
    await _log_activity(
        session,
        tenant_id=tenant_id,
        deal_id=deal.id,
        kind="deal_stage_changed",
        detail={"from": previous, "to": stage},
        actor_user_id=actor_user_id,
    )
    await session.flush()
    return deal


async def list_deals(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[DealRow], int]:
    total = (
        await session.execute(
            select(func.count()).select_from(Deal).where(Deal.tenant_id == tenant_id)
        )
    ).scalar_one()
    stmt = (
        select(Deal, Contact)
        .join(Contact, Contact.id == Deal.contact_id)
        .where(Deal.tenant_id == tenant_id)
        .order_by(Deal.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    return [
        DealRow(
            id=d.id,
            contact_email=crypto.decrypt(c.email_encrypted),
            title=d.title,
            stage=d.stage,
            amount=d.amount,
            currency=d.currency,
            created_at=d.created_at,
        )
        for d, c in rows
    ], total


@dataclass(frozen=True, slots=True)
class DealRow:
    id: uuid.UUID
    contact_email: str
    title: str
    stage: str
    amount: Decimal | None
    currency: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TaskRow:
    id: uuid.UUID
    title: str
    due_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NoteRow:
    id: uuid.UUID
    body: str
    author_email: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityRow:
    id: uuid.UUID
    kind: str
    detail: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DealDetail:
    deal: DealRow
    tasks: list[TaskRow]
    notes: list[NoteRow]
    activities: list[ActivityRow]


async def get_deal_detail(
    session: AsyncSession, crypto: CryptoBox, *, tenant_id: uuid.UUID, deal_id: uuid.UUID
) -> DealDetail:
    deal = await session.get(Deal, deal_id)
    if deal is None or deal.tenant_id != tenant_id:
        raise NotFound("No such deal.")
    contact = await session.get(Contact, deal.contact_id)
    if contact is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such contact.")

    tasks = (
        (
            await session.execute(
                select(Task).where(Task.deal_id == deal_id).order_by(Task.created_at)
            )
        )
        .scalars()
        .all()
    )
    note_rows = (
        await session.execute(
            select(Note, User)
            .join(User, User.id == Note.author_user_id)
            .where(Note.deal_id == deal_id)
            .order_by(Note.created_at.desc())
        )
    ).all()
    activity_rows = (
        (
            await session.execute(
                select(Activity)
                .where(Activity.deal_id == deal_id)
                .order_by(Activity.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return DealDetail(
        deal=DealRow(
            id=deal.id,
            contact_email=crypto.decrypt(contact.email_encrypted),
            title=deal.title,
            stage=deal.stage,
            amount=deal.amount,
            currency=deal.currency,
            created_at=deal.created_at,
        ),
        tasks=[
            TaskRow(id=t.id, title=t.title, due_at=t.due_at, completed_at=t.completed_at)
            for t in tasks
        ],
        notes=[
            NoteRow(
                id=n.id,
                body=n.body,
                author_email=crypto.decrypt(u.email_encrypted),
                created_at=n.created_at,
            )
            for n, u in note_rows
        ],
        activities=[
            ActivityRow(id=a.id, kind=a.kind, detail=a.detail, created_at=a.created_at)
            for a in activity_rows
        ],
    )


async def create_task(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    deal_id: uuid.UUID,
    title: str,
    due_at: datetime | None,
    assigned_to_user_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
) -> Task:
    deal = await session.get(Deal, deal_id)
    if deal is None or deal.tenant_id != tenant_id:
        raise NotFound("No such deal.")
    task = Task(
        id=uuid7(),
        tenant_id=tenant_id,
        deal_id=deal_id,
        title=title,
        due_at=due_at,
        assigned_to_user_id=assigned_to_user_id,
    )
    session.add(task)
    await _log_activity(
        session,
        tenant_id=tenant_id,
        deal_id=deal_id,
        kind="task_created",
        detail={"title": title},
        actor_user_id=actor_user_id,
    )
    await session.flush()
    return task


async def complete_task(
    session: AsyncSession, *, tenant_id: uuid.UUID, task_id: uuid.UUID, actor_user_id: uuid.UUID
) -> Task:
    task = await session.get(Task, task_id)
    if task is None or task.tenant_id != tenant_id:
        raise NotFound("No such task.")
    if task.completed_at is not None:
        raise DealError("This task is already complete.")
    task.completed_at = datetime.now(UTC)
    await _log_activity(
        session,
        tenant_id=tenant_id,
        deal_id=task.deal_id,
        kind="task_completed",
        detail={"title": task.title},
        actor_user_id=actor_user_id,
    )
    await session.flush()
    return task


async def add_note(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    deal_id: uuid.UUID,
    body: str,
    author_user_id: uuid.UUID,
) -> Note:
    deal = await session.get(Deal, deal_id)
    if deal is None or deal.tenant_id != tenant_id:
        raise NotFound("No such deal.")
    note = Note(
        id=uuid7(), tenant_id=tenant_id, deal_id=deal_id, body=body, author_user_id=author_user_id
    )
    session.add(note)
    await _log_activity(
        session,
        tenant_id=tenant_id,
        deal_id=deal_id,
        kind="note_added",
        detail={},
        actor_user_id=author_user_id,
    )
    await session.flush()
    return note


__all__ = [
    "ActivityRow",
    "DealDetail",
    "DealError",
    "DealRow",
    "NoteRow",
    "TaskRow",
    "add_note",
    "complete_task",
    "create_deal",
    "create_task",
    "get_deal_detail",
    "list_deals",
    "set_stage",
]
