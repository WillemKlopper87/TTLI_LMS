"""`cohort:run` — the permission POST/GET /cohorts (0047) actually checks.

0047 built the programmes routers and services against `cohort:run`
throughout, but never registered it as a real permission — no row in
`permissions`, no grant in `role_permissions`. Every caller, including
the break-glass super_admin account, would 403 on every cohort
endpoint: `Principal.require`/the permission-set check in
`list_cohorts` are plain frozenset membership tests with no
super-admin bypass, so an unregistered permission string is
unusable by anyone regardless of role.

Granted to admin and super_admin, mirroring 0022's product:manage
precedent — scheduling a cohort (assigning a facilitator and seats
for an organisation) is an operational/admin action, not a
content-authoring one, so not granted to content_author.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION = "cohort:run"
DESCRIPTION = "Create and manage cohorts (scheduled programme runs)"
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
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = :p"),
        {"p": PERMISSION},
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE code = :p"), {"p": PERMISSION})
