"""Phase 5 sprint 3: workshops, facilitators, booking (02 §9, REQ-WS-01
through REQ-WS-09).

Full vertical slice for one complete booking path: a facilitator with a
weekly availability calendar, a workshop offering real bookable
sessions, capacity enforcement with a real waitlist (REQ-WS-03),
facilitator-overridable attendance (REQ-WS-08), and a pluggable meeting
provider (REQ-WS-06) — `manual` fully working today, `teams` structured
correctly but refusing cleanly without real Graph API credentials
(`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`/`GRAPH_TENANT_ID`), the exact
same "real interface, blocked on external creds" shape Phase 3's
Payfast/Netcash card checkout already established — not a fabricated
integration pretending to work.

Deliberately deferred, both real gaps rather than silent omissions:
- REQ-WS-04 (credit-based booking) — `entitlements.kind` already
  anticipates `workshop_credit`/`coaching_credit` (02 §6.3's own field
  list), but consuming a credit needs quantity-decrement semantics
  `entitlements` doesn't have yet (today's `revoked_at` is all-or-
  nothing, not a partial draw-down). Sessions in this sprint are
  open-enrolment instead — booking, capacity, waitlist and attendance
  are real; charging a credit per booking is the next increment.
- REQ-WS-09 (post-workshop survey) — reuses `surveys` (already fully
  built in Phase 4 sprint 3) rather than a new `workshop_feedback`
  table duplicating it; wiring a session to an existing survey is a
  smaller follow-up than this sprint, not a new subsystem.

Reschedule (part of REQ-WS-03) is modelled as cancel-then-rebook against
a different session, not a dedicated `rescheduled_from_id` chain — the
`attendance_status` enum already carries a `rescheduled` value for
exactly this, so the state is recorded even though the two bookings
aren't linked yet.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = (
    "facilitators",
    "facilitator_availability",
    "workshops",
    "workshop_sessions",
    "bookings",
    "meeting_links",
    "attendance_records",
)

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

NEW_PERMISSIONS: list[tuple[str, str]] = [
    ("workshop:manage", "Create and manage workshops, sessions and facilitators"),
    ("workshop:facilitate", "Run assigned sessions and record attendance"),
]


def upgrade() -> None:
    bind = op.get_bind()
    # Each enum is used by exactly one table below, so SQLAlchemy's default
    # create-on-first-use is enough — no separate `.create()` pass needed
    # (that would create the type twice and fail the second attempt).
    session_type = sa.Enum(*SESSION_TYPE_VALUES, name="workshop_session_type")
    session_status = sa.Enum(*SESSION_STATUS_VALUES, name="workshop_session_status")
    booking_status = sa.Enum(*BOOKING_STATUS_VALUES, name="booking_status")
    meeting_provider = sa.Enum(*MEETING_PROVIDER_VALUES, name="meeting_provider")
    attendance_status = sa.Enum(*ATTENDANCE_STATUS_VALUES, name="attendance_status")

    op.create_table(
        "facilitators",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="UTC"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_facilitators_tenant_id", "facilitators", ["tenant_id"])
    op.create_index(
        "uq_facilitators_tenant_user", "facilitators", ["tenant_id", "user_id"], unique=True
    )

    op.create_table(
        "facilitator_availability",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "facilitator_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("facilitators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 0 = Monday .. 6 = Sunday (Python's own date.weekday()), so the
        # service layer never has to translate conventions.
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_availability_day_of_week"),
        sa.CheckConstraint("end_time > start_time", name="ck_availability_end_after_start"),
    )
    op.create_index(
        "ix_facilitator_availability_facilitator_id", "facilitator_availability", ["facilitator_id"]
    )
    op.create_index(
        "ix_facilitator_availability_tenant_id", "facilitator_availability", ["tenant_id"]
    )

    op.create_table(
        "workshops",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("session_type", session_type, nullable=False),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_workshops_tenant_id", "workshops", ["tenant_id"])

    op.create_table(
        "workshop_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "workshop_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workshops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "facilitator_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("facilitators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("status", session_status, nullable=False, server_default="scheduled"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_sessions_end_after_start"),
        sa.CheckConstraint("capacity > 0", name="ck_sessions_capacity_positive"),
    )
    op.create_index("ix_workshop_sessions_tenant_id", "workshop_sessions", ["tenant_id"])
    op.create_index("ix_workshop_sessions_workshop_id", "workshop_sessions", ["workshop_id"])
    op.create_index(
        "ix_workshop_sessions_facilitator_starts",
        "workshop_sessions",
        ["facilitator_id", "starts_at"],
    )

    op.create_table(
        "bookings",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workshop_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", booking_status, nullable=False, server_default="registered"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_bookings_tenant_id", "bookings", ["tenant_id"])
    op.create_index("ix_bookings_session_id", "bookings", ["session_id"])
    op.create_index("uq_bookings_session_user", "bookings", ["session_id", "user_id"], unique=True)

    op.create_table(
        "meeting_links",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workshop_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", meeting_provider, nullable=False),
        sa.Column("provider_meeting_id", sa.Text(), nullable=True),
        sa.Column("join_url", sa.Text(), nullable=True),
        sa.Column(
            "organiser_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_meeting_links_tenant_id", "meeting_links", ["tenant_id"])
    op.create_index("uq_meeting_links_session_id", "meeting_links", ["session_id"], unique=True)

    op.create_table(
        "attendance_records",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "booking_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", attendance_status, nullable=False, server_default="registered"),
        # 02 §9's own distinction: what Graph/Zoom/Meet reported, versus a
        # facilitator's manual override, which always wins (REQ-WS-08).
        sa.Column("source", sa.Text(), nullable=False, server_default="facilitator_manual"),
        sa.Column(
            "recorded_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('provider_report', 'facilitator_manual')", name="ck_attendance_source"
        ),
    )
    op.create_index("ix_attendance_records_tenant_id", "attendance_records", ["tenant_id"])
    op.create_index(
        "uq_attendance_records_booking_id", "attendance_records", ["booking_id"], unique=True
    )

    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    for code, description in NEW_PERMISSIONS:
        bind.execute(
            sa.text("INSERT INTO permissions (code, description) VALUES (:c, :d)"),
            {"c": code, "d": description},
        )
    bind.execute(sa.text("INSERT INTO roles (code, name) VALUES ('facilitator', 'Facilitator')"))
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_code, permission_code) VALUES "
            "('facilitator', 'workshop:facilitate'), "
            "('admin', 'workshop:manage'), ('admin', 'workshop:facilitate'), "
            "('super_admin', 'workshop:manage'), ('super_admin', 'workshop:facilitate')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_code IN "
            "('workshop:manage', 'workshop:facilitate')"
        )
    )
    bind.execute(sa.text("DELETE FROM role_assignments WHERE role_code = 'facilitator'"))
    bind.execute(sa.text("DELETE FROM roles WHERE code = 'facilitator'"))
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code IN ('workshop:manage', 'workshop:facilitate')")
    )

    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_table("attendance_records")
    op.drop_table("meeting_links")
    op.drop_table("bookings")
    op.drop_table("workshop_sessions")
    op.drop_table("workshops")
    op.drop_table("facilitator_availability")
    op.drop_table("facilitators")

    for enum_name in (
        "attendance_status",
        "meeting_provider",
        "booking_status",
        "workshop_session_status",
        "workshop_session_type",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
