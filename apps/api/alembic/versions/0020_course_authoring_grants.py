"""Course/module/lesson authoring — the write grants `app_user` never
had (Phase 4's authoring gap, `docs/STATUS.md`). `0011` left `courses`/
`modules`/`lessons` in its `READ_ONLY` set on purpose, since nothing
wrote to them through the app yet; `0012` and `0014` each added one
narrow `UPDATE` grant as one narrow endpoint needed it (video/quiz/
survey/assignment attachment, manager-visibility). This migration is
the same pattern, generalized now that real authoring endpoints exist:
`courses` and `lessons` gain `INSERT` (their `UPDATE` already exists);
`modules` gains both, since nothing has ever written to it before.

No schema change, no new table, no new RLS policy — `courses`/`modules`/
`lessons` are the global, non-tenant-scoped catalogue (`src/models/
course.py`'s own docstring), so there is no tenant-isolation policy to
add here, only the missing grants.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.execute(f"GRANT INSERT ON courses TO {APP_ROLE}")
    op.execute(f"GRANT INSERT, UPDATE ON modules TO {APP_ROLE}")
    op.execute(f"GRANT INSERT ON lessons TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ON courses FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE ON modules FROM {APP_ROLE}")
    op.execute(f"REVOKE INSERT ON lessons FROM {APP_ROLE}")
