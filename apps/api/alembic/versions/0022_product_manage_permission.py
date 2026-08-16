"""`product:manage` — the permission that lets an authored course be sold
(frontend backlog item 5).

No schema change. `products`/`prices` already carry full `app_user` grants
(0009 created them, 0021's subscription authoring is what first wrote to
them), and `Product.course_id` — the actual course→commerce bridge — has
existed since 0011. The only thing missing was the authority to write any
of it: every product in the database up to now was planted by a migration,
so a freshly authored course could never be bought.

Deliberately *not* granted to `content_author`, even though 0002 grants
that role the neighbouring `subscription_plan:manage`. Setting a price is
a commercial decision, not a content one. That makes this migration mildly
inconsistent with an existing grant on purpose; the alternative is widening
pricing authority to every content author as a side effect of adding an
unrelated screen. If `content_author` should price things, decide that
explicitly and grant it — don't infer it from the subscription precedent.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION = "product:manage"
DESCRIPTION = "Create and price products, and make courses purchasable"
ROLES = ("admin", "super_admin")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES (:c, :d) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"c": PERMISSION, "d": DESCRIPTION},
    )
    for role in ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_code, permission_code) "
                "VALUES (:r, :p) ON CONFLICT DO NOTHING"
            ),
            {"r": role, "p": PERMISSION},
        )


def downgrade() -> None:
    conn = op.get_bind()
    # role_permissions first: it has an FK onto permissions, so removing
    # the permission row while assignments still reference it would fail.
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = :p"),
        {"p": PERMISSION},
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE code = :p"), {"p": PERMISSION})
