"""Reading the audit log (`docs/research/enterprise-gaps-plan.md` Pass B).

Kept apart from `services/audit.py` on purpose: that module is the write
path and its whole point is being narrow — one function, no update path,
mirroring a table the database refuses to mutate. Reading is a different
concern with filters, pagination and decryption in it, and folding the
two together would blur what `audit.record` is allowed to do.

`app_user` already holds SELECT on `audit_events` (0001), so nothing
here needs a new grant. RLS scopes rows to the tenant; every query also
filters `tenant_id` explicitly, the same belt-and-braces the rest of the
admin reads use.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.models.audit import AuditEvent
from src.models.user import User
from src.schemas.audit import AuditEventRow, AuditEventsPage
from src.services.reports import _mask_email

# One screen of a scannable table. The CSV export path takes its own,
# larger cap — a compliance reviewer asking for a range wants the range,
# not 50 rows of it.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
EXPORT_LIMIT = 10_000


def encode_cursor(created_at: datetime, event_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{event_id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    """None for anything unparseable. A malformed cursor is a client
    mistake, not a server error: the caller gets page one rather than a
    500, which is also what a stale bookmarked cursor deserves."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        stamp, _, event_id = raw.partition("|")
        return datetime.fromisoformat(stamp), uuid.UUID(event_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def _filtered(
    tenant_id: uuid.UUID,
    *,
    action: str | None,
    actor_user_id: uuid.UUID | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select[tuple[AuditEvent, bytes | None]]:
    # Outer join: an audit row can name an actor who has since been
    # deleted, and — more commonly — carry no actor at all (a failed
    # login knows no user, a webhook rejection has no session). An inner
    # join would silently drop exactly the rows a reviewer most wants.
    # The outer join makes the email column nullable in reality; the
    # mapped attribute is typed non-optional, so the cast keeps the
    # annotation honest about what a row can actually contain.
    stmt = cast(
        "Select[tuple[AuditEvent, bytes | None]]",
        select(AuditEvent, User.email_encrypted)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.tenant_id == tenant_id),
    )
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if actor_user_id is not None:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if entity_type is not None:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if date_from is not None:
        stmt = stmt.where(AuditEvent.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditEvent.created_at < date_to)
    return stmt


def _row(crypto: CryptoBox, event: AuditEvent, email_encrypted: bytes | None) -> AuditEventRow:
    return AuditEventRow(
        id=event.id,
        created_at=event.created_at,
        action=event.action,
        actor_user_id=event.actor_user_id,
        actor_role=event.actor_role,
        actor_email=_actor_email(crypto, email_encrypted),
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        before=event.before,
        after=event.after,
        ip=str(event.ip) if event.ip is not None else None,
        user_agent=event.user_agent,
    )


def _actor_email(crypto: CryptoBox, email_encrypted: bytes | None) -> str | None:
    """Masked, and a decrypt failure degrades to a marker rather than
    breaking the page — some dev rows are encrypted under a since-rotated
    key (docs/STATUS.md §10), and an audit reader that 500s on historical
    data is worse than useless."""
    if email_encrypted is None:
        return None
    try:
        return _mask_email(crypto.decrypt(email_encrypted))
    except Exception:
        return "(unreadable — key rotated)"


async def list_events(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> AuditEventsPage:
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = _filtered(
        tenant_id,
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
    )

    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is not None:
            last_at, last_id = decoded
            # Strictly "older than the last row I saw", with id breaking
            # ties so two events written in the same microsecond can
            # never straddle a page boundary.
            stmt = stmt.where(
                or_(
                    AuditEvent.created_at < last_at,
                    and_(AuditEvent.created_at == last_at, AuditEvent.id < last_id),
                )
            )

    # One extra row is the cheapest possible "is there more?" — no second
    # COUNT query over a table that only grows.
    rows = (
        await session.execute(
            stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1][0].created_at, page[-1][0].id) if has_more and page else None
    )
    return AuditEventsPage(
        items=[_row(crypto, event, email) for event, email in page],
        next_cursor=next_cursor,
    )


async def export_rows(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[AuditEventRow]:
    """The same filters as the screen, capped. Built from the same query
    builder so an export can never disagree with what was on screen —
    the rule `routers/analytics.py` already established for its CSV
    twins."""
    stmt = _filtered(
        tenant_id,
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
    )
    rows = (
        await session.execute(
            stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(EXPORT_LIMIT)
        )
    ).all()
    return [_row(crypto, event, email) for event, email in rows]


async def distinct_actions(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[str]:
    rows = (
        await session.execute(
            select(AuditEvent.action)
            .where(AuditEvent.tenant_id == tenant_id)
            .group_by(AuditEvent.action)
            .order_by(AuditEvent.action)
        )
    ).scalars()
    return list(rows)


def day_bounds(day_from: str | None, day_to: str | None) -> tuple[datetime | None, datetime | None]:
    """`YYYY-MM-DD` in, half-open UTC window out. `to` is inclusive of the
    named day, so a reviewer asking for the 1st to the 3rd gets the 3rd."""
    start = datetime.fromisoformat(day_from).replace(tzinfo=UTC) if day_from else None
    end = None
    if day_to:
        parsed = datetime.fromisoformat(day_to).replace(tzinfo=UTC)
        end = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


async def count_events(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id == tenant_id)
            )
        ).scalar_one()
    )


__all__ = [
    "count_events",
    "day_bounds",
    "decode_cursor",
    "distinct_actions",
    "encode_cursor",
    "export_rows",
    "list_events",
]
