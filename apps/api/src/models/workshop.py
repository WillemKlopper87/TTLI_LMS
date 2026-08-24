"""Workshops, facilitators, booking (02 §9, REQ-WS-01 through REQ-WS-09).
See `0018`'s migration docstring for what this sprint deliberately
deferred (credit-based booking, the dedicated feedback table) and why.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

SESSION_TYPE_VALUES = ("one_on_one", "group_workshop", "cohort_session", "assessment_debrief")
SESSION_STATUS_VALUES = ("scheduled", "cancelled", "completed")
BOOKING_STATUS_VALUES = ("registered", "waitlisted", "cancelled")
MEETING_PROVIDER_VALUES = ("manual", "teams", "zoom", "meet")
ATTENDANCE_STATUS_VALUES = (
    "registered",
    "joined",
    "attended",
    "partially_attended",
    "no_show",
    "cancelled",
    "rescheduled",
)

# create_type=False: 0018 creates these Postgres enum types explicitly,
# once — same reasoning as commerce.py's OrderStatus.
WorkshopSessionType = Enum(*SESSION_TYPE_VALUES, name="workshop_session_type", create_type=False)
WorkshopSessionStatus = Enum(
    *SESSION_STATUS_VALUES, name="workshop_session_status", create_type=False
)
BookingStatus = Enum(*BOOKING_STATUS_VALUES, name="booking_status", create_type=False)
MeetingProvider = Enum(*MEETING_PROVIDER_VALUES, name="meeting_provider", create_type=False)
AttendanceStatus = Enum(*ATTENDANCE_STATUS_VALUES, name="attendance_status", create_type=False)


class Facilitator(Base, TimestampMixin):
    __tablename__ = "facilitators"
    __table_args__ = (Index("uq_facilitators_tenant_user", "tenant_id", "user_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")


class FacilitatorAvailability(Base):
    __tablename__ = "facilitator_availability"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_availability_day_of_week"),
        CheckConstraint("end_time > start_time", name="ck_availability_end_after_start"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    facilitator_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("facilitators.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 0 = Monday .. 6 = Sunday (Python's date.weekday()) — the service
    # layer never has to translate conventions.
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Workshop(Base, TimestampMixin):
    __tablename__ = "workshops"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_type: Mapped[str] = mapped_column(WorkshopSessionType, nullable=False)
    default_duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    # P7 (docs/BACKLOG.md): opt-in per workshop, default false — every
    # existing workshop keeps today's open/free booking behaviour
    # untouched. True means book_session requires (and consumes) a
    # workshop_credit entitlement targeting this workshop.
    requires_credit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Which MeetingProvider book_session should use for this workshop's
    # sessions — previously hardcoded to "manual" in the service layer;
    # this column is what makes that a real per-workshop choice (P7).
    meeting_provider: Mapped[str] = mapped_column(
        MeetingProvider, nullable=False, server_default="manual"
    )


class WorkshopSession(Base, TimestampMixin):
    __tablename__ = "workshop_sessions"
    __table_args__ = (
        Index("ix_workshop_sessions_facilitator_starts", "facilitator_id", "starts_at"),
        CheckConstraint("ends_at > starts_at", name="ck_sessions_end_after_start"),
        CheckConstraint("capacity > 0", name="ck_sessions_capacity_positive"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    workshop_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workshops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No index=True: the composite index above already covers
    # facilitator_id lookups as its leftmost column.
    facilitator_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("facilitators.id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        WorkshopSessionStatus, nullable=False, server_default="scheduled"
    )


class SessionFacilitator(Base):
    """Co-facilitators on a session (P7, docs/BACKLOG.md; REQ-WS-02/03)
    — additive alongside `WorkshopSession.facilitator_id`, not a
    replacement for it. `facilitator_id` stays the organiser/primary
    pointer (Graph meeting organiser, `MeetingLink` provenance); this
    table is what makes "every facilitator on this session" a query
    instead of always being exactly one row. The primary facilitator is
    backfilled into this table too (`0036`), so listing a session's
    facilitators is always this table alone, never `facilitator_id`
    unioned with it."""

    __tablename__ = "session_facilitators"
    __table_args__ = (
        Index("uq_session_facilitators", "session_id", "facilitator_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workshop_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    facilitator_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("facilitators.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (Index("uq_bookings_session_user", "session_id", "user_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workshop_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(BookingStatus, nullable=False, server_default="registered")
    # `0027` — set once by due_workshop_reminders() (SECURITY DEFINER),
    # never by application code directly; null means "not yet reminded,"
    # not "no reminder is due."
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # P7: which workshop_credit Entitlement this booking drew from, if
    # the workshop required one — null for every open/free booking
    # (the vast majority). Provenance only, same reasoning
    # PathEnrolment.entitlement_id (0035) already established: lets
    # cancel refund the exact entitlement a booking consumed, not just
    # "some" entitlement for this workshop.
    consumed_entitlement_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entitlements.id", ondelete="RESTRICT"), nullable=True
    )


class MeetingLink(Base):
    __tablename__ = "meeting_links"
    __table_args__ = (Index("uq_meeting_links_session_id", "session_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workshop_sessions.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(MeetingProvider, nullable=False)
    provider_meeting_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    join_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    organiser_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        Index("uq_attendance_records_booking_id", "booking_id", unique=True),
        CheckConstraint(
            "source IN ('provider_report', 'facilitator_manual')", name="ck_attendance_source"
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        AttendanceStatus, nullable=False, server_default="registered"
    )
    # What 02 §9 distinguishes: a provider's own report versus a
    # facilitator's manual override, which always wins (REQ-WS-08).
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="facilitator_manual")
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = [
    "ATTENDANCE_STATUS_VALUES",
    "BOOKING_STATUS_VALUES",
    "MEETING_PROVIDER_VALUES",
    "SESSION_STATUS_VALUES",
    "SESSION_TYPE_VALUES",
    "AttendanceRecord",
    "AttendanceStatus",
    "Booking",
    "BookingStatus",
    "Facilitator",
    "FacilitatorAvailability",
    "MeetingLink",
    "MeetingProvider",
    "SessionFacilitator",
    "Workshop",
    "WorkshopSession",
    "WorkshopSessionStatus",
    "WorkshopSessionType",
]
