"""`assessment:run`, `assessment:analyse`, `report:submit`, `report:review`
— the four permissions 0047's analyst-workspace routers check throughout,
never registered as real permissions.

Same gap 0048 closes on feat/programmes for `cohort:run`: no row in
`permissions`, no grant in `role_permissions`, so every analyst-workspace
endpoint 403s for every caller regardless of role — `Principal.require`
and the permission-set checks in `get_report`/`list_reports` are plain
frozenset membership tests, and the break-glass super_admin account has
no bypass around them.

There is no dedicated analyst/reviewer role yet (0002's ROLES has
guest/learner/content_author/finance/admin/super_admin only) — deciding
whether "analyst" and "reviewer" deserve their own roles, versus folding
this into `admin`, is a product/RBAC design question this migration
doesn't try to settle. Granting all four to `admin` and `super_admin`
for now keeps the feature usable; splitting them onto a narrower role
later needs its own migration, not a guess baked in here.

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = (
    ("assessment:run", "Assign and revoke analyst engagements on assessment instances"),
    ("assessment:analyse", "Read assessment results as an analyst"),
    ("report:submit", "Author and submit analyst reports"),
    ("report:review", "Review, return, accept and release analyst reports"),
)
ROLES = ("admin", "super_admin")


def upgrade() -> None:
    conn = op.get_bind()
    for code, description in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO permissions (code, description) VALUES (:c, :d) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"c": code, "d": description},
        )
        for role in ROLES:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_code, permission_code) "
                    "VALUES (:r, :p) ON CONFLICT DO NOTHING"
                ),
                {"r": role, "p": code},
            )


def downgrade() -> None:
    conn = op.get_bind()
    codes = [code for code, _ in PERMISSIONS]
    for code in codes:
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_code = :p"),
            {"p": code},
        )
        conn.execute(sa.text("DELETE FROM permissions WHERE code = :p"), {"p": code})
