"""Articles / blog (`docs/research/resources-hub-design.md` §2) — the one
content type the resources hub's stage-1 pass identified as genuinely
absent from the data model: long-form written content with no curriculum,
no completion rules and no pricing, closest in shape to `podcast_episodes`
(`0026`) rather than `courses`.

Tenant-scoped for the same reason `podcast_episodes` is: this is
tenant-specific marketing/thought-leadership content, not shared catalogue.
`state` reuses the existing `content_state` enum — identical closed set,
no reason to duplicate it (matches `0026`'s own reasoning).

`published_at` is set on the transition to `published`, not on row
creation — see `services/articles.py`. `reading_minutes` is computed at
that same transition from a ~200wpm heuristic, the estimate
`course_wizard.py` already uses for lesson duration.

No `access_level`/gating column, matching `podcast_episodes` — every
article is public by design once published; no gated-content unlock
mechanism exists anywhere in this codebase yet for any content type
(`0026`'s own docstring covers why building one here would be scope
creep).

Permission: reuses `podcast:manage` rather than adding a new
`content:manage` (design doc §4 decision 1) — article authoring is the
same "content author curates the marketing surface" job podcast curation
already is, and a second permission code buys no real separation of
duties today.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"

# Reused, not created here — see 0026's own precedent for reusing this type.
CONTENT_STATE_VALUES = ("draft", "in_review", "approved", "published", "archived")


def upgrade() -> None:
    content_state = pg.ENUM(*CONTENT_STATE_VALUES, name="content_state", create_type=False)

    op.create_table(
        "articles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        # One-line summary shown in the rowlist/card — optional, distinct
        # from `body`.
        sa.Column("dek", sa.Text(), nullable=True),
        # Markdown, rendered client-side. Author-authenticated content
        # (podcast:manage-gated), not user input — same trust boundary as
        # podcast_episodes.show_notes/transcript.
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("cover_image_object_key", sa.Text(), nullable=True),
        # Free text, not a user FK — TTLI publishes under facilitator
        # names that may not have platform accounts.
        sa.Column("author_name", sa.Text(), nullable=True),
        sa.Column(
            "related_course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("state", content_state, nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reading_minutes", sa.Integer(), nullable=True),
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
    op.create_index("ix_articles_tenant_id", "articles", ["tenant_id"])
    op.create_index("uq_articles_tenant_slug", "articles", ["tenant_id", "slug"], unique=True)
    op.create_index(
        "ix_articles_tenant_state_position", "articles", ["tenant_id", "state", "position"]
    )

    op.execute("ALTER TABLE articles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE articles FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON articles
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    # No DELETE — an article is archived via `state`, never hard-deleted,
    # the same convention podcast_episodes/courses already follow.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON articles TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("articles")
