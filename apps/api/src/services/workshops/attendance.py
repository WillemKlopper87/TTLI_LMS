"""Facilitator-recorded attendance and the session roster. Split out of
the former monolithic `services/workshops.py` (TTLI_Audit_Report_2026-09-02.md
M6); see `src/services/workshops/__init__.py` for the split's rationale.
Fully self-contained — no cross-module calls into authoring/booking/reporting.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.crypto import CryptoBox
from src.core.errors import NotFound
from src.models.user import User
from src.models.workshop import ATTENDANCE_STATUS_VALUES, AttendanceRecord, Booking
from src.services.workshops.errors import WorkshopError


async def mark_attendance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str,
    recorded_by_user_id: uuid.UUID,
) -> AttendanceRecord:
    if status not in ATTENDANCE_STATUS_VALUES:
        raise WorkshopError(f"Unknown attendance status: {status}")
    booking = (
        await session.execute(
            select(Booking).where(Booking.session_id == session_id, Booking.user_id == user_id)
        )
    ).scalar_one_or_none()
    if booking is None or booking.tenant_id != tenant_id:
        raise NotFound("No booking for this learner and session.")

    record = (
        await session.execute(
            select(AttendanceRecord).where(AttendanceRecord.booking_id == booking.id)
        )
    ).scalar_one_or_none()
    if record is None:  # pragma: no cover - booking always creates one
        raise NotFound("No attendance record for this booking.")

    record.status = status
    record.source = "facilitator_manual"
    record.recorded_by_user_id = recorded_by_user_id
    record.recorded_at = datetime.now(UTC)
    await session.flush()
    return record


@dataclass(frozen=True, slots=True)
class RosterRow:
    booking_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    booking_status: str
    attendance_status: str


async def list_roster(
    session: AsyncSession, crypto: CryptoBox, *, session_id: uuid.UUID
) -> list[RosterRow]:
    stmt = (
        select(Booking, User, AttendanceRecord)
        .join(User, User.id == Booking.user_id)
        .join(AttendanceRecord, AttendanceRecord.booking_id == Booking.id)
        .where(Booking.session_id == session_id)
        .order_by(Booking.created_at)
    )
    rows = (await session.execute(stmt)).all()
    return [
        RosterRow(
            booking_id=b.id,
            user_id=u.id,
            email=crypto.decrypt(u.email_encrypted),
            booking_status=b.status,
            attendance_status=a.status,
        )
        for b, u, a in rows
    ]


__all__ = ["RosterRow", "list_roster", "mark_attendance"]
