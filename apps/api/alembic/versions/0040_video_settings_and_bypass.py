"""Video upload/transcode workflow redesign.

Splits video upload into two phases (`routers/media.py::upload_video_asset`
now creates a `state="draft"` row with a size estimate per rung instead of
immediately enqueueing a transcode; a new `finalize` endpoint then either
enqueues a transcode with an admin-chosen rung selection or marks the
asset `state="ready"` with the original file served as-is). Also adds a
tenant->course->per-upload settings chain for which rungs are offered by
default and whether the as-is bypass is allowed at all.

New `video_assets` columns:
- `source_content_type`, `source_filename`, `source_size_bytes` — upload
  provenance, captured once at upload time. Needed because `get_object`
  has no way to hand content-type back to the caller on read (checked all
  three storage adapters) — persisting it here is what makes serving the
  original file as-is possible without guessing a media type from a file
  extension the way `get_hls_file` already does for HLS output.
- `estimated_sizes` (jsonb) — `{rung: bytes}` computed once from the
  ffprobe duration against `LADDER`'s bitrates, shown to the admin before
  they commit to a rung selection.
- `requested_rungs` (jsonb) — the admin's actual choice, read by
  `services/media/pipeline.py` instead of the previously-hardcoded
  `DEFAULT_RUNGS`.
- `delivery_mode` — `"hls"` (transcoded, the only mode that existed
  before this migration) or `"progressive"` (as-is bypass, served by the
  new `GET /media/{id}/original` route).
- `course_id` — nullable, advisory: set from an optional form field at
  upload time so the tenant->course settings chain can be resolved before
  the admin has decided anything, and re-checked at finalize time so the
  as-is bypass can't be granted based on a client-supplied course id that
  drifted from what the decision panel actually showed.

New `courses.video_settings` column (jsonb, same shape/precedent as
`completion_rules`): `{rungs: [...], allow_bypass: bool}`, the course-level
tier of the fallback chain (course -> tenant -> hardcoded default).

No grant changes — both tables are already fully granted (0012, 0020).

Revision ID: 0040
Revises: 0039
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("video_assets", sa.Column("source_content_type", sa.Text(), nullable=True))
    op.add_column("video_assets", sa.Column("source_filename", sa.Text(), nullable=True))
    op.add_column("video_assets", sa.Column("source_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column(
        "video_assets",
        sa.Column(
            "estimated_sizes",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "video_assets",
        sa.Column(
            "requested_rungs",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "video_assets",
        sa.Column("delivery_mode", sa.String(length=16), nullable=False, server_default="hls"),
    )
    op.add_column("video_assets", sa.Column("course_id", pg.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_video_assets_course_id",
        "video_assets",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "courses",
        sa.Column(
            "video_settings",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("courses", "video_settings")

    op.drop_constraint("fk_video_assets_course_id", "video_assets", type_="foreignkey")
    op.drop_column("video_assets", "course_id")
    op.drop_column("video_assets", "delivery_mode")
    op.drop_column("video_assets", "requested_rungs")
    op.drop_column("video_assets", "estimated_sizes")
    op.drop_column("video_assets", "source_size_bytes")
    op.drop_column("video_assets", "source_filename")
    op.drop_column("video_assets", "source_content_type")
