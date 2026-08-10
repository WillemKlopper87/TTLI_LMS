"""Phase 5 sprint 2: manager visibility (02 §4.5, REQ-TEN-03, 04 §2.3's
P2 policy). The demo target itself: "a manager who cannot see individual
scores until an admin enables it for one course."

No new tables. `courses.manager_visibility` (`0011`) and
`tenants.settings` (`0001`) already exist — this migration adds the
third of REQ-TEN-03's three conditions, the "explicit permission":

    manager.organisation_id = learner.organisation_id
    AND manager has team:reports:view_individual
    AND course.manager_visibility = individual_enabled
    AND tenant.settings.allow_manager_individual_results = true

`team:reports:view_individual` is granted here to `admin`/`super_admin`
only — a platform-staff override for support/oversight. An organisation's
own manager satisfies the "explicit permission" condition through their
`organisation_members.relationship` (`manager`/`admin`) instead of a
tenant-wide RBAC role: RBAC roles in this codebase are tenant-scoped, not
per-organisation, so granting this permission through `role_assignments`
would let a manager in one organisation see another organisation's
individual results — exactly what the first ABAC condition
(`manager.organisation_id = learner.organisation_id`) exists to prevent.
`organisation_members.relationship` is already the per-organisation grant
mechanism 0016 built for exactly this kind of standing (`services/
reports.py` is where both paths are checked).

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION_CODE = "team:reports:view_individual"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("INSERT INTO permissions (code, description) VALUES (:c, :d)"),
        {
            "c": PERMISSION_CODE,
            "d": "View individual learner results across any organisation in the tenant",
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_code, permission_code) VALUES "
            "('admin', :c), ('super_admin', :c)"
        ),
        {"c": PERMISSION_CODE},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = :c"), {"c": PERMISSION_CODE}
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": PERMISSION_CODE})
