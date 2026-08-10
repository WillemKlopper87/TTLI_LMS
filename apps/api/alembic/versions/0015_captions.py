"""Phase 4.5: WebVTT captions (01 §3.4 REQ-LMS-07, §6.6). One column.

`video_assets` already has a full `SELECT, INSERT, UPDATE, DELETE` grant
from `0012` — a caption file is just another attribute of the asset, not
a new access pattern, so no grant changes are needed here.

Captions are served through the exact same signed-URL mechanism HLS
segments already use (`GET /media/{id}/hls/{filename}`, `services/media/
playback.py`) rather than a new endpoint: a `<track>` element is subject
to the same "the browser can't set an Authorization header" constraint
06 §3.2 already solved for segments, so `captions.vtt` is stored under
the asset's own `video-assets/{id}/` prefix and fetched with the same
short-lived playback token — no new entitlement logic to get wrong.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("video_assets", sa.Column("caption_object_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("video_assets", "caption_object_key")
