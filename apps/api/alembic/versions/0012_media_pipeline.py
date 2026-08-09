"""Phase 4 sprint 2: video_assets, transcode_jobs, video_progress and
video_heartbeats (02 §5.4/5.5/7.3/7.4) — the tables behind the ported VOD
transcode pipeline and heartbeat-validated watch progress.

`video_assets`/`transcode_jobs` are **not** tenant-scoped, matching
`courses`/`modules`/`lessons` (0011) — a video asset belongs to a lesson,
which belongs to a globally-shared course. `video_progress` and
`video_heartbeats` are tenant-scoped: they belong to one tenant's
enrolment, even though the video itself is shared.

No FK from `transcode_jobs` back to `video_assets` — 02 §5.5 doesn't
document one; `video_assets.transcode_job_id` is the only link, and the
worker (`src/workers/main.py::transcode_video_job`) is handed
`video_asset_id` directly as its job argument rather than needing to
derive it.

`video_heartbeats` is described as "append-only" in 02 §7.4, but unlike
`ledger_entries`/`audit_events`/`consent_records` (02 §1.5's actual
append-only list) it gets the plain grant, not the two-layer trigger
enforcement — same treatment `events` (0004) already got despite similar
prose elsewhere, and not worth a second enforcement mechanism for a table
nothing ever updates in practice. Left un-partitioned this sprint too:
02 §7.4 names monthly partitioning as "the first partitioning candidate,"
not a day-one requirement, and the 90-day retention sweep that would
consume it isn't built either — same class of deferral as the guest-
expiry downgrade sweep (STATUS.md).

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("video_progress", "video_heartbeats")


def upgrade() -> None:
    op.create_table(
        "transcode_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "processed_seconds", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "video_assets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "transcode_job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("transcode_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("playlist_object_key", sa.Text(), nullable=True),
        sa.Column(
            "renditions", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column("state", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.add_column(
        "lessons",
        sa.Column(
            "video_asset_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("video_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "video_progress",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "enrolment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("enrolments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "furthest_position_seconds",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "watched_seconds", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("heartbeat_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_video_progress_tenant_id", "video_progress", ["tenant_id"])
    op.create_index(
        "uq_video_progress_enrolment_lesson",
        "video_progress",
        ["enrolment_id", "lesson_id"],
        unique=True,
    )

    op.create_table(
        "video_heartbeats",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "enrolment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("enrolments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position_seconds", sa.Numeric(10, 2), nullable=False),
        sa.Column("playback_rate", sa.Numeric(4, 2), nullable=False, server_default=sa.text("1.0")),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_video_heartbeats_tenant_id", "video_heartbeats", ["tenant_id"])
    op.create_index(
        "ix_video_heartbeats_enrolment_lesson", "video_heartbeats", ["enrolment_id", "lesson_id"]
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

    # Not tenant-scoped — global catalogue tables, same reasoning as
    # courses/modules/lessons (0011). No authoring endpoint restricts
    # video_assets/transcode_jobs writes yet beyond course:edit at the API
    # layer, so app_user needs the full grant here (unlike 0011's
    # read-only courses/modules/lessons, which have no writer this sprint).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON video_assets TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON transcode_jobs TO {APP_ROLE}")

    # lessons gets its first real writer this sprint: POST /lessons/{id}/
    # video (routers/media.py), a narrow single-field UPDATE, not general
    # authoring — so UPDATE only, not INSERT/DELETE. 0011 left lessons
    # (along with courses/modules) SELECT-only because nothing wrote to
    # them yet; this is that grant catching up with the first real writer.
    op.execute(f"GRANT UPDATE ON lessons TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ON lessons FROM {APP_ROLE}")
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("video_heartbeats")
    op.drop_table("video_progress")
    op.drop_column("lessons", "video_asset_id")
    op.drop_table("video_assets")
    op.drop_table("transcode_jobs")
