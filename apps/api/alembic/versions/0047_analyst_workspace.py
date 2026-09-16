"""Analyst workspace: engagement and report state machine (BACKLOG L5).

Revision ID: 0047
Revises: 0046

The analyst workspace enables in-house staff and contracted analysts to work on
assessment results within the platform. Engagements grant analysts time-windowed
access to specific assessment instances, and reports flow through a state machine
(draft → submitted → returned/accepted/withdrawn) for review by organisation owners.

This migration creates:
- assessment_engagements: time-windowed assignment of analysts to instances
- reports: state machine tracking report lifecycle (draft/submitted/returned/accepted/withdrawn)
- report_attachments: PDF/PPTX uploads for reports (virus-scanned, stored in private container)

Key design decisions:
- instance_id on both tables is a nullable UUID WITHOUT a database-level foreign key
  constraint. The assessment_platform feature (built on a separate branch) provides the
  instances table; this branch adds the columns as a deferred cross-feature FK to be
  added when both branches integrate after Sprint 1 closes. We add a comment in the
  code models to explain this.
- RLS policies enforce tenant isolation on both tables (assessment_engagements and reports).
- The partial unique index on assessment_engagements(instance_id, analyst_user_id)
  WHERE revoked_at IS NULL ensures only one active engagement per analyst/instance pair.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("assessment_engagements", "reports", "report_attachments")


def upgrade() -> None:
    # Create enum for report status
    report_status_enum = postgresql.ENUM(
        "draft", "submitted", "returned", "accepted", "withdrawn",
        name="report_status",
        create_type=False,
    )
    report_status_enum.create(op.get_bind())

    # --- assessment_engagements table ---
    op.create_table(
        "assessment_engagements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        # Deferred cross-feature FK to assessment_platform.instances.id.
        # Added as plain UUID without constraint; will be converted to full FK after
        # both branches integrate following Sprint 1.
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "analyst_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Partial unique index: one active engagement per analyst/instance pair
    op.create_index(
        "uq_assessment_engagements_instance_analyst_active",
        "assessment_engagements",
        ["instance_id", "analyst_user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # --- reports table ---
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        # Deferred cross-feature FK to assessment_platform.instances.id.
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assessment_engagements.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", report_status_enum, nullable=False, server_default="draft"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # --- report_attachments table ---
    op.create_table(
        "report_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Virus-scanned before the file is readable (same fail-closed rule as
        # assignment uploads in 0013).
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_result", sa.String(16), nullable=True),
    )

    # --- Enable RLS on tenant-scoped tables ---
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


def downgrade() -> None:
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("report_attachments")
    op.drop_table("reports")
    op.drop_table("assessment_engagements")
    op.execute("DROP TYPE IF EXISTS report_status")
