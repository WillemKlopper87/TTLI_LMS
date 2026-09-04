"""Block-based lesson content builder.

Replaces the one-activity-per-lesson model (`lessons.activity_type` plus
a single nullable FK per type — video/quiz/survey/assignment — and
`lessons.body` for documents) with a new `lesson_blocks` child table: a
lesson now holds an ordered sequence of blocks of any type, in any order
and any quantity, instead of exactly one activity. Also adds `audio_assets`
— a new, first-class audio block type, deliberately not a `video_assets`
variant (no transcode ladder, no renditions, no delivery_mode, no
`transcode_jobs` row; every asset is stored-and-served exactly as
uploaded, matching `video_assets.delivery_mode="progressive"`'s bypass
shape from 0040 minus the "or transcode instead" branch audio has no
equivalent bandwidth-ladder problem to justify).

Neither new table is tenant-scoped, matching `lessons`/`video_assets`
(0011/0012) — a lesson block belongs to a lesson, which belongs to a
globally-shared course.

`video_progress`/`video_heartbeats` move their identity/uniqueness key
from `lesson_id` to the new `lesson_block_id`: with more than one video
block now possible per lesson, keying on `lesson_id` alone would collide
heartbeats/progress from two different video blocks in the same lesson
into one row. `lesson_id` is kept on both tables (not dropped) since some
queries still want "every progress row in this lesson" without a join.

Backfill: exactly one `lesson_blocks` row per pre-existing lesson,
`position=0`, carrying over `body`/the four FKs, mapping
`activity_type="document"` to the new `block_type="text"` (every other
value is unchanged). IDs are generated in Python via a local `_uuid7()`
helper (same convention as 0011/0009's seed data — the app's own
`uuid7()` isn't reachable from a migration, and `gen_random_uuid()` would
produce a real v4/v7 inconsistency in the same table going forward).

This is a single atomic cutover, not a staged rollout: the four `lessons`
columns are dropped in this same migration, so every reader of them
(services/routers/schemas across courses, media, assessment, enrolment,
course_wizard) must land in the same change as this migration — see the
plan doc for the full list. No long-lived backward-compat shim.

`downgrade()` is lossless only for lessons that still have exactly one
block (the pre-migration shape) — a lesson that gained additional blocks
after upgrading cannot downgrade losslessly. That's fine: downgrade is a
rollback-before-real-use path here, not a supported "add blocks then go
back" path.

Revision ID: 0041
Revises: 0040
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def _uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


def upgrade() -> None:
    op.create_table(
        "audio_assets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("source_content_type", sa.Text(), nullable=True),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON audio_assets TO {APP_ROLE}")

    op.create_table(
        "lesson_blocks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lesson_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(32), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "video_asset_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("video_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "audio_asset_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("audio_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "quiz_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("quizzes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "survey_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("surveys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assignment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_lesson_blocks_lesson_position", "lesson_blocks", ["lesson_id", "position"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON lesson_blocks TO {APP_ROLE}")

    # Backfill: one block per existing lesson, position=0, activity_type
    # "document" maps to the new "text" block_type, everything else is
    # unchanged.
    conn = op.get_bind()
    lessons = conn.execute(
        sa.text(
            "SELECT id, activity_type, body, video_asset_id, quiz_id, survey_id, assignment_id "
            "FROM lessons"
        )
    ).fetchall()
    for lesson in lessons:
        block_type = "text" if lesson.activity_type == "document" else lesson.activity_type
        conn.execute(
            sa.text(
                "INSERT INTO lesson_blocks "
                "(id, lesson_id, position, block_type, body, video_asset_id, "
                " quiz_id, survey_id, assignment_id) "
                "VALUES (:id, :lesson_id, 0, :block_type, :body, :video_asset_id, "
                " :quiz_id, :survey_id, :assignment_id)"
            ),
            {
                "id": _uuid7(),
                "lesson_id": lesson.id,
                "block_type": block_type,
                "body": lesson.body,
                "video_asset_id": lesson.video_asset_id,
                "quiz_id": lesson.quiz_id,
                "survey_id": lesson.survey_id,
                "assignment_id": lesson.assignment_id,
            },
        )

    # video_progress/video_heartbeats move their identity key from
    # lesson_id to lesson_block_id (see module docstring). Add nullable,
    # backfill from the one block just created per lesson, then tighten.
    op.add_column("video_progress", sa.Column("lesson_block_id", pg.UUID(as_uuid=True)))
    op.add_column("video_heartbeats", sa.Column("lesson_block_id", pg.UUID(as_uuid=True)))
    conn.execute(
        sa.text(
            "UPDATE video_progress SET lesson_block_id = lb.id "
            "FROM lesson_blocks lb WHERE lb.lesson_id = video_progress.lesson_id"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE video_heartbeats SET lesson_block_id = lb.id "
            "FROM lesson_blocks lb WHERE lb.lesson_id = video_heartbeats.lesson_id"
        )
    )
    op.alter_column("video_progress", "lesson_block_id", nullable=False)
    op.alter_column("video_heartbeats", "lesson_block_id", nullable=False)
    op.create_foreign_key(
        "fk_video_progress_lesson_block_id",
        "video_progress",
        "lesson_blocks",
        ["lesson_block_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_video_heartbeats_lesson_block_id",
        "video_heartbeats",
        "lesson_blocks",
        ["lesson_block_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("uq_video_progress_enrolment_lesson", table_name="video_progress")
    op.create_index(
        "uq_video_progress_enrolment_block",
        "video_progress",
        ["enrolment_id", "lesson_block_id"],
        unique=True,
    )
    op.drop_index("ix_video_heartbeats_enrolment_lesson", table_name="video_heartbeats")
    op.create_index(
        "ix_video_heartbeats_enrolment_block",
        "video_heartbeats",
        ["enrolment_id", "lesson_block_id"],
    )

    # Cutover: drop the now-redundant lessons columns. Unnamed
    # column-owned FKs (video_asset_id/quiz_id/survey_id/assignment_id
    # were all added via inline sa.ForeignKey, never a named
    # create_foreign_key) drop automatically with the column on Postgres
    # — same convention 0013's own downgrade() already relies on.
    op.drop_column("lessons", "activity_type")
    op.drop_column("lessons", "body")
    op.drop_column("lessons", "video_asset_id")
    op.drop_column("lessons", "quiz_id")
    op.drop_column("lessons", "survey_id")
    op.drop_column("lessons", "assignment_id")


def downgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("activity_type", sa.String(32), nullable=False, server_default="document"),
    )
    op.add_column("lessons", sa.Column("body", sa.Text(), nullable=True))
    op.add_column(
        "lessons",
        sa.Column(
            "video_asset_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("video_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "quiz_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("quizzes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "survey_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("surveys.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "assignment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE lessons SET "
            " activity_type = CASE WHEN lb.block_type = 'text' THEN 'document' "
            "                      ELSE lb.block_type END, "
            " body = lb.body, video_asset_id = lb.video_asset_id, "
            " quiz_id = lb.quiz_id, survey_id = lb.survey_id, "
            " assignment_id = lb.assignment_id "
            "FROM lesson_blocks lb "
            "WHERE lb.lesson_id = lessons.id AND lb.position = 0"
        )
    )

    op.drop_index("ix_video_heartbeats_enrolment_block", table_name="video_heartbeats")
    op.create_index(
        "ix_video_heartbeats_enrolment_lesson", "video_heartbeats", ["enrolment_id", "lesson_id"]
    )
    op.drop_index("uq_video_progress_enrolment_block", table_name="video_progress")
    op.create_index(
        "uq_video_progress_enrolment_lesson",
        "video_progress",
        ["enrolment_id", "lesson_id"],
        unique=True,
    )
    op.drop_constraint(
        "fk_video_heartbeats_lesson_block_id", "video_heartbeats", type_="foreignkey"
    )
    op.drop_constraint("fk_video_progress_lesson_block_id", "video_progress", type_="foreignkey")
    op.drop_column("video_heartbeats", "lesson_block_id")
    op.drop_column("video_progress", "lesson_block_id")

    op.drop_table("lesson_blocks")
    op.execute(f"REVOKE ALL ON audio_assets FROM {APP_ROLE}")
    op.drop_table("audio_assets")
