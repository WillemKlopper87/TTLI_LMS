"""Podcast platform (REQ-STORE-04, expanded per `docs/research/podcast-
platform-integration.md` §5) — TTLI's own episodes plus admin-curated
third-party recommendations, replacing the "not built yet" placeholder
`02_DATA_MODEL.md` §5.6 named for `podcast_episodes`.

Tenant-scoped, unlike the global `courses` table: podcast curation is
tenant-specific marketing content, closer to `leads`/`campaigns` than to
the shared course catalogue that deliberately stays unduplicated per
tenant (02 §1.3's carve-out is for *shared catalogue* rows specifically,
which this isn't).

Deliberately **no `access_level` column**, unlike `lessons`. The research
doc's own open-questions section flags that a gated-content unlock
mechanism (lead-capture-gated content, REQ-STORE-05's second tier) does
not exist anywhere in this codebase yet, for any content type — building
one from scratch as a side effect of this migration would be a much
larger, separate feature than what was actually asked for (embed/share
TTLI's own episodes, let an admin curate third-party "recommended"
episodes, capture listen stats). `01_PRD.md`'s own framing of podcasts as
"a sales lure" backs treating every episode as public by design here —
`state` alone (draft/published/archived, the same `ContentState` enum
`courses` already uses) gates whether it appears on the public page at
all. Add gating later, once the shared unlock mechanism REQ-STORE-03's
resource hub will also need actually exists, rather than half-building it
twice.

`kind` ('authored' | 'curated') is a plain String, not a new Postgres
enum — matching `payments.provider`'s more recently-established
convention for a small, stable, closed set over `courses.py`'s older
`ContentState`/`AccessLevel` true-enum style; both are defensible, this
follows the newer precedent. `state` *does* reuse the existing
`content_state` enum type (`create_type=False`, same as `courses.state`)
since it's the identical closed set with no reason to duplicate it.

No `access_level`/gating means no new unlock endpoint either — everything
below is either a public read or a `podcast:manage`-gated write, the same
two-permission-tier shape `courses.py`'s router already uses for
`course:view`... except there is no public/private read split to gate at
all here, so no `podcast:view` permission is added; `podcast:manage` is
the only new permission, granted to the same three roles `course:edit`
already is (`content_author`, `admin`, `super_admin`) since podcast
curation is a content-authoring action, not a commercial one (unlike
`product:manage`, deliberately withheld from `content_author` in `0022`).

Revision ID: 0026
Revises: 0025
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
PERMISSION = "podcast:manage"
PERMISSION_DESCRIPTION = "Create, edit, publish and curate podcast episodes"
PERMISSION_ROLES = ("content_author", "admin", "super_admin")

# The real values behind the already-created `content_state` Postgres enum
# (0011) — create_type=False below reuses that existing type rather than
# trying to create it again; passing the values (not an empty list) is
# what every other migration reusing an enum type already does (0009,
# 0013, 0014, 0021).
CONTENT_STATE_VALUES = ("draft", "in_review", "approved", "published", "archived")


def upgrade() -> None:
    content_state = pg.ENUM(*CONTENT_STATE_VALUES, name="content_state", create_type=False)

    op.create_table(
        "podcast_episodes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # 'authored' (TTLI's own, self-hosted audio) | 'curated' (a
        # third-party episode, embed-only — see the module docstring).
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", content_state, nullable=False, server_default="draft"),
        # 'authored' only — the actual REQ-STORE-04 requirement an embed
        # alone cannot satisfy (Spotify's iframe gives a player, not a
        # transcript or show notes TTLI can own and render).
        sa.Column("show_notes", sa.Text(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column(
            "related_course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Self-hosted audio ('authored' only) — Container.PUBLIC_MARKETING,
        # no transcode ladder: see services/podcasts.py's own docstring for
        # why this deliberately does not reuse the video pipeline.
        sa.Column("audio_object_key", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("cover_image_object_key", sa.Text(), nullable=True),
        # Which platform external_url/external_embed_id point at — both
        # 'authored' (a "also on Spotify" cross-post link) and 'curated'
        # (the primary listen path) use these.
        sa.Column("external_platform", sa.String(32), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("external_embed_id", sa.Text(), nullable=True),
        # 'curated' only — the "recommended by [host]" attribution the
        # product owner explicitly asked for.
        sa.Column("curator_name", sa.Text(), nullable=True),
        sa.Column("curator_note", sa.Text(), nullable=True),
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
    op.create_index("ix_podcast_episodes_tenant_id", "podcast_episodes", ["tenant_id"])
    op.create_index(
        "uq_podcast_episodes_tenant_slug", "podcast_episodes", ["tenant_id", "slug"], unique=True
    )
    # The public listing's own query shape: published episodes for a
    # tenant, ordered for display — matches ix_lessons_module_position's
    # reasoning for a composite over two singles.
    op.create_index(
        "ix_podcast_episodes_tenant_state_position",
        "podcast_episodes",
        ["tenant_id", "state", "position"],
    )

    op.execute("ALTER TABLE podcast_episodes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE podcast_episodes FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON podcast_episodes
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    # SELECT/INSERT/UPDATE only, no DELETE — courses/modules/lessons' own
    # grant (verified directly against the live schema while writing this
    # migration) never included DELETE either; an episode is archived via
    # `state`, never hard-deleted, the same REQ-ADMIN-02 convention.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON podcast_episodes TO {APP_ROLE}")

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES (:c, :d) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"c": PERMISSION, "d": PERMISSION_DESCRIPTION},
    )
    for role in PERMISSION_ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_code, permission_code) "
                "VALUES (:r, :p) ON CONFLICT DO NOTHING"
            ),
            {"r": role, "p": PERMISSION},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = :p"), {"p": PERMISSION}
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE code = :p"), {"p": PERMISSION})
    op.drop_table("podcast_episodes")
