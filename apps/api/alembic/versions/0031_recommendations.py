"""Recommendations (`docs/research/resources-hub-design.md` §3) — stage 3
of the resources hub, a short list of external "further reading" links
(books, papers, other people's articles) with a one-line editorial note.

Distinct from a curated `PodcastEpisode` (`kind == "curated"`): today that
is the only "recommendation" surface, which forces every recommendation to
be shaped like a podcast episode (a `duration_seconds`, an embed path) even
when it is really "here is an article, go read it." This table drops
everything episode-shaped — no body, no reading time, no slug, no detail
page, just an external link and a note (see the design doc §3.1's own
comparison table).

Tenant-scoped and RLS/grant-shaped identically to `podcast_episodes`
(`0026`) and `articles` (`0030`) — same reasoning, not repeated here.
Reuses the `podcast:manage` permission (matches `0030`'s decision for
articles: this is the same "content author curates the marketing surface"
job, not a new authoring domain).

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"

CONTENT_STATE_VALUES = ("draft", "in_review", "approved", "published", "archived")


def upgrade() -> None:
    content_state = pg.ENUM(*CONTENT_STATE_VALUES, name="content_state", create_type=False)

    op.create_table(
        "recommendations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        # Same free-text pattern as podcast_episodes.curator_name — not a
        # user FK, TTLI attributes recommendations to facilitators who may
        # not have platform accounts.
        sa.Column("curator_name", sa.Text(), nullable=True),
        sa.Column("curator_note", sa.Text(), nullable=True),
        sa.Column(
            "related_course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("state", content_state, nullable=False, server_default="draft"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_recommendations_tenant_id", "recommendations", ["tenant_id"])
    op.create_index(
        "ix_recommendations_tenant_state_position",
        "recommendations",
        ["tenant_id", "state", "position"],
    )

    op.execute("ALTER TABLE recommendations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE recommendations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON recommendations
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    # No DELETE — archived via state, same convention as articles/podcasts.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON recommendations TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("recommendations")
