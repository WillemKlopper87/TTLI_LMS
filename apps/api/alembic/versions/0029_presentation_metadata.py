"""Course presentation metadata for the public catalogue and the learner
dashboard (the approved 11-screen prototype), plus the DELETE grants the
course-authoring wizard's delete endpoints need.

Three things:

1. `GRANT DELETE ON lessons, modules TO app_user` — `routers/course_wizard.py`
   deletes modules/lessons (with a progress guard); `0020` only ever
   granted INSERT/UPDATE. Applied by hand in the dev DB earlier; this
   makes it permanent and reversible.

2. New nullable presentation columns on `courses`: `summary` (a one-
   paragraph lead), `level` ('introductory' | 'intermediate' | 'executive'),
   `topic`, `format` ('self_paced' | 'blended' | 'live_cohort'), `outcomes`
   (jsonb list of strings, default `[]`), `includes_workshop` (bool,
   default false), and `hero_colour` (a hex like '#3E4A3C' for the
   catalogue card's art block). All optional — nothing existing needs them.
   `courses` is the global, non-tenant-scoped catalogue (`src/models/
   course.py`), so there is no RLS to touch.

3. Seed the two demo courses (`executive-leadership-certificate` from
   0009/0011 and `executive-coaching-intensive` from 0021) with realistic
   values in the prototype's voice, so the catalogue/landing screens have
   something to render in dev. Scoped by slug, exactly like those seeds;
   the downgrade drops the columns, which is the whole reversal.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"

# slug -> presentation metadata. Not real TTLI curriculum — the same
# "structural demo content" precedent 0009/0011/0021 set.
SEED: dict[str, dict[str, object]] = {
    "executive-leadership-certificate": {
        "summary": (
            "A leadership programme for people who already carry the decisions — "
            "built around the judgement calls you actually face, not the ones "
            "in the textbook."
        ),
        "level": "executive",
        "topic": "Leadership",
        "format": "blended",
        "outcomes": [
            "Make and communicate a decision when the data is incomplete, "
            "without pretending it isn't",
            "Run a hard conversation so that the other person leaves knowing where they stand",
            "Tell the difference between a team that is busy and a team that is delivering",
            "Hold a line under pressure from above without losing the people below you",
        ],
        "includes_workshop": True,
        "hero_colour": "#3E4A3C",
    },
    "executive-coaching-intensive": {
        "summary": (
            "A short, intensive programme on coaching the people you lead — "
            "asking better questions, listening for what isn't said, and "
            "letting others own the answer."
        ),
        "level": "executive",
        "topic": "Leadership",
        "format": "blended",
        "outcomes": [
            "Coach a capable person through a problem without solving it for them",
            "Ask the one question that moves a stuck conversation",
            "Give feedback that is specific enough to act on and kind enough to hear",
            "Know when coaching is the wrong tool, and what to reach for instead",
        ],
        "includes_workshop": False,
        "hero_colour": "#5B4A3E",
    },
}


def upgrade() -> None:
    op.execute(f"GRANT DELETE ON lessons, modules TO {APP_ROLE}")

    op.add_column("courses", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("courses", sa.Column("level", sa.String(length=32), nullable=True))
    op.add_column("courses", sa.Column("topic", sa.String(length=64), nullable=True))
    op.add_column("courses", sa.Column("format", sa.String(length=32), nullable=True))
    op.add_column(
        "courses",
        sa.Column(
            "outcomes",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "courses",
        sa.Column(
            "includes_workshop",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("courses", sa.Column("hero_colour", sa.String(length=16), nullable=True))

    conn = op.get_bind()
    for slug, meta in SEED.items():
        conn.execute(
            sa.text(
                "UPDATE courses SET summary = :summary, level = :level, topic = :topic, "
                "format = :format, outcomes = CAST(:outcomes AS jsonb), "
                "includes_workshop = :includes_workshop, hero_colour = :hero_colour "
                "WHERE slug = :slug"
            ),
            {
                "slug": slug,
                "summary": meta["summary"],
                "level": meta["level"],
                "topic": meta["topic"],
                "format": meta["format"],
                "outcomes": json.dumps(meta["outcomes"]),
                "includes_workshop": meta["includes_workshop"],
                "hero_colour": meta["hero_colour"],
            },
        )


def downgrade() -> None:
    op.drop_column("courses", "hero_colour")
    op.drop_column("courses", "includes_workshop")
    op.drop_column("courses", "outcomes")
    op.drop_column("courses", "format")
    op.drop_column("courses", "topic")
    op.drop_column("courses", "level")
    op.drop_column("courses", "summary")

    op.execute(f"REVOKE DELETE ON lessons, modules FROM {APP_ROLE}")
