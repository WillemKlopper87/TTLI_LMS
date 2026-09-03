"""Record which tenant authored a course/learning path (H-12 fix).

`courses`/`learning_paths` are deliberately global, not tenant-scoped
(0011/0035's own migration docstrings) -- `course_tenant_assignments`/
`learning_path_tenant_assignments` are what make one visible to a
tenant, and those two join tables carry FORCE ROW LEVEL SECURITY. That
turns out to make them unusable as the sole "is this course still
unclaimed, mid-authoring" signal for the cross-tenant authoring boundary
`services/courses.py`/`services/learning_paths.py` now enforce: a query
against a FORCE-RLS table, run inside tenant B's own request
transaction, cannot see tenant A's row *at all* -- not filtered out by a
WHERE clause, filtered out by Postgres before the row is ever visible to
this connection. So "no assignment row is visible to me" is true both
for a genuinely unclaimed course and for one already bespoke to a
different tenant, and a boundary that can't tell those apart isn't one.

`created_by_tenant_id` is the fix: set once, by the API, at creation
time, on `courses`/`learning_paths` themselves -- tables with no RLS at
all, so every tenant's session can read it. The boundary becomes "the
tenant that created this row, or a tenant with an explicit assignment
to it" -- both determinable without ever needing to see another
tenant's row. Nullable and left NULL on every pre-existing row (the
0011 seed course included, already assignment-only) -- no backfill
possible, since nothing recorded who authored a course before this
column existed; `course_authorable`/`path_authorable` fall back to the
assignment-only check for a NULL creator, exactly the behaviour those
rows already had.

`ON DELETE SET NULL`, not `RESTRICT`: this column is provenance, not a
foreign-key relationship anything else depends on existing for — a
tenant being deleted must not be blocked by (or silently drag down) a
global course/path any other tenant might still hold.

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "created_by_tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_courses_created_by_tenant_id", "courses", ["created_by_tenant_id"]
    )
    op.add_column(
        "learning_paths",
        sa.Column(
            "created_by_tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_learning_paths_created_by_tenant_id", "learning_paths", ["created_by_tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_learning_paths_created_by_tenant_id", table_name="learning_paths")
    op.drop_column("learning_paths", "created_by_tenant_id")
    op.drop_index("ix_courses_created_by_tenant_id", table_name="courses")
    op.drop_column("courses", "created_by_tenant_id")
