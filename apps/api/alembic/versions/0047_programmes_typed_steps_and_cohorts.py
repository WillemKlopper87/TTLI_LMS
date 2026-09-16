"""Programmes (entry paths) — typed steps and cohorts (first slice).

Revision ID: 0047
Revises: 0046

Part 1 of the programmes feature (docs/superpowers/specs/2026-09-11-programmes-design.md §7):
one week for typed steps and the cohorts table.

### 2.1 Typed steps

`learning_path_steps` replaces `learning_path_courses` with a `kind` enum
('course'|'workshop'|'assessment'|'one_on_one'|'document'). Migration is 1:1:
every existing `learning_path_courses` row becomes a `kind='course'` step; the
learner path UI keeps working unchanged because course steps are structurally
identical to the old courses.

### 2.2 Programme runs (cohorts)

A run is a scheduled instantiation of a learning path for an organisation with
participants. Three tables: `cohorts` (the run itself), `cohort_steps` (the
run's instantiation of each path step with scheduling info), `cohort_members`
(participants).

`cohort_steps.assessment_instance_id` is a plain nullable UUID **without** a
database-level foreign-key constraint to the not-yet-existing
assessment_instances table (added in a separate feature branch). It will be
constrained when both branches merge. See code comment on the column.

All tenant-scoped tables have RLS policies following 0035's pattern.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("cohorts", "cohort_steps", "cohort_members")


def _uuid7() -> uuid.UUID:
    """Generate a UUID7 for use during data migration."""
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


def upgrade() -> None:
    # --- learning_path_steps: replace learning_path_courses ----
    # Step kind enum: course, workshop, assessment, one_on_one, document.
    step_kind = pg.ENUM(
        "course",
        "workshop",
        "assessment",
        "one_on_one",
        "document",
        name="learning_path_step_kind",
        create_type=True,
    )

    op.create_table(
        "learning_path_steps",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "learning_path_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", step_kind, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("phase_label", sa.Text(), nullable=True),
        sa.Column("optional", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "workshop_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workshops.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "assessment_template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_templates.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("evaluation_role", sa.String(32), nullable=True),  # 'pre', 'post', or NULL
        sa.Column(
            "completion_rules",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_learning_path_steps_learning_path_id", "learning_path_steps", ["learning_path_id"])
    op.create_index(
        "uq_learning_path_steps_position",
        "learning_path_steps",
        ["learning_path_id", "position"],
        unique=True,
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON learning_path_steps TO {APP_ROLE}")

    # Backfill: one course step per existing learning_path_course row,
    # migrating title from the course itself.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT lpc.id, lpc.learning_path_id, lpc.position, lpc.course_id, c.title "
            "FROM learning_path_courses lpc "
            "JOIN courses c ON c.id = lpc.course_id "
            "ORDER BY lpc.learning_path_id, lpc.position"
        )
    ).fetchall()

    for old_id, path_id, position, course_id, course_title in rows:
        conn.execute(
            sa.text(
                "INSERT INTO learning_path_steps "
                "(id, learning_path_id, position, kind, title, course_id) "
                "VALUES (:id, :path_id, :position, 'course', :title, :course_id)"
            ),
            {
                "id": _uuid7(),
                "path_id": path_id,
                "position": position,
                "title": course_title,
                "course_id": course_id,
            },
        )

    # Drop learning_path_courses now that it's migrated.
    op.drop_table("learning_path_courses")

    # --- cohorts, cohort_steps, cohort_members ----
    cohort_status = pg.ENUM(
        "planned",
        "active",
        "completed",
        "cancelled",
        name="cohort_status",
        create_type=True,
    )

    cohort_step_status = pg.ENUM(
        "pending",
        "scheduled",
        "in_progress",
        "done",
        "skipped",
        name="cohort_step_status",
        create_type=True,
    )

    cohort_member_role = pg.ENUM(
        "participant",
        "observer",
        name="cohort_member_role",
        create_type=True,
    )

    op.create_table(
        "cohorts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "learning_path_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "organisation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column(
            "lead_facilitator_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", cohort_status, nullable=False, server_default="planned"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_cohorts_tenant_id", "cohorts", ["tenant_id"])
    op.create_index("ix_cohorts_learning_path_id", "cohorts", ["learning_path_id"])
    op.create_index("ix_cohorts_organisation_id", "cohorts", ["organisation_id"])

    op.create_table(
        "cohort_steps",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cohort_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_path_steps.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", cohort_step_status, nullable=False, server_default="pending"),
        sa.Column(
            "workshop_session_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("workshop_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Deferred foreign key: will be constrained when assessment_instances table lands.
        # This is a plain nullable UUID without DB-level constraint for now.
        sa.Column("assessment_instance_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_cohort_steps_cohort_id", "cohort_steps", ["cohort_id"])
    op.create_index("ix_cohort_steps_step_id", "cohort_steps", ["step_id"])

    op.create_table(
        "cohort_members",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cohort_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "path_enrolment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("path_enrolments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("role", cohort_member_role, nullable=False, server_default="participant"),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_cohort_members_cohort_id", "cohort_members", ["cohort_id"])
    op.create_index("ix_cohort_members_user_id", "cohort_members", ["user_id"])

    # Grant permissions on all three tenant-scoped tables.
    for table in ("cohorts", "cohort_steps", "cohort_members"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    # RLS policies: cohorts and cohort_members are tenant-scoped.
    # cohort_steps doesn't have tenant_id directly but is accessed through cohorts.
    for table in ("cohorts", "cohort_members"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )

    # cohort_steps: RLS via the cohort_id -> cohorts.tenant_id join
    op.execute("ALTER TABLE cohort_steps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cohort_steps FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON cohort_steps
        USING (
            cohort_id IN (
                SELECT id FROM cohorts
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
        )
        WITH CHECK (
            cohort_id IN (
                SELECT id FROM cohorts
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
        )
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON cohort_steps TO {APP_ROLE}")


def downgrade() -> None:
    # Drop tenant-scoped table RLS policies.
    for table in ("cohorts", "cohort_members", "cohort_steps"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")

    op.drop_table("cohort_members")
    op.drop_table("cohort_steps")
    op.drop_table("cohorts")

    # Recreate learning_path_courses from learning_path_steps.
    op.create_table(
        "learning_path_courses",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "learning_path_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_learning_path_courses_learning_path_id",
        "learning_path_courses",
        ["learning_path_id"],
    )
    op.create_index(
        "uq_learning_path_courses",
        "learning_path_courses",
        ["learning_path_id", "course_id"],
        unique=True,
    )

    # Backfill: restore learning_path_courses from course steps.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, learning_path_id, position, course_id "
            "FROM learning_path_steps "
            "WHERE kind = 'course' "
            "ORDER BY learning_path_id, position"
        )
    ).fetchall()

    for step_id, path_id, position, course_id in rows:
        conn.execute(
            sa.text(
                "INSERT INTO learning_path_courses "
                "(id, learning_path_id, position, course_id) "
                "VALUES (:id, :path_id, :position, :course_id)"
            ),
            {
                "id": step_id,
                "path_id": path_id,
                "position": position,
                "course_id": course_id,
            },
        )

    op.drop_table("learning_path_steps")
    op.execute(f"REVOKE ALL ON learning_path_steps FROM {APP_ROLE}")
    op.execute("DROP TYPE IF EXISTS learning_path_step_kind")
    op.execute("DROP TYPE IF EXISTS cohort_status")
    op.execute("DROP TYPE IF EXISTS cohort_step_status")
    op.execute("DROP TYPE IF EXISTS cohort_member_role")
