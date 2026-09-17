"""Add dedicated `analyst` and `reviewer` roles.

0048 granted `assessment:run`/`assessment:analyse`/`report:submit`/
`report:review` only to `admin`/`super_admin` as a deliberate interim,
noting that a real analyst/reviewer role was a product/RBAC decision it
wasn't trying to settle. Operationally, that interim means the only way
to let someone author or review analyst reports is to make them a full
tenant admin — too broad for what's meant to be a narrow, time-windowed
engagement. This migration settles it: `analyst` (assessment:analyse +
report:submit) and `reviewer` (report:review) as their own roles, on
top of — not instead of — the existing admin/super_admin grants.

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES: dict[str, tuple[str, list[str]]] = {
    "analyst": ("Analyst", ["assessment:analyse", "report:submit"]),
    "reviewer": ("Reviewer", ["report:review"]),
}


def upgrade() -> None:
    conn = op.get_bind()
    for code, (name, perms) in ROLES.items():
        conn.execute(
            sa.text(
                "INSERT INTO roles (code, name) VALUES (:c, :n) ON CONFLICT (code) DO NOTHING"
            ),
            {"c": code, "n": name},
        )
        for perm in perms:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_code, permission_code) "
                    "VALUES (:r, :p) ON CONFLICT DO NOTHING"
                ),
                {"r": code, "p": perm},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for code in ROLES:
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE role_code = :r"), {"r": code}
        )
        conn.execute(sa.text("DELETE FROM roles WHERE code = :c"), {"c": code})
