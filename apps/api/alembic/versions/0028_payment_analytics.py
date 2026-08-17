"""Payment & Revenue Analytics dashboard (docs/research/payment-analytics-
dashboard.md §5, §2) — indexes only, plus one permission grant.

No new tables or columns, and deliberately no stored aggregate/rollup
table: the dashboard aggregates over the existing normalised commerce
tables (`orders`, `payments`, `ledger_entries`, `subscriptions`, `users`)
at request time, scoped by tenant and a resolved UTC period. What those
queries filter and group on had no covering index — every existing index
on these tables is a bare `tenant_id` or an FK column — so this adds the
five composites the research doc enumerated after reading each table's
actual index list. Each is mirrored in the model's `__table_args__` so
`alembic check` (CI's drift gate) sees model and database agree.

The permission side: `analytics:view` has existed since 0002, granted to
`admin` and `super_admin` only. The dashboard is a finance-facing
report, and `finance` is the role that will actually live in it, so this
migration also grants `analytics:view` to `finance` — the research doc
flagged this as its first open question and recommended it; the build
instruction for this feature named finance explicitly. Reversible: the
downgrade removes only that one `role_permissions` row (never the
`admin`/`super_admin` grants 0002 seeded, and never the permission row
itself).

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION = "analytics:view"
NEW_ROLE = "finance"

INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_orders_tenant_status_created", "orders", ["tenant_id", "status", "created_at"]),
    ("ix_orders_tenant_organisation", "orders", ["tenant_id", "organisation_id"]),
    ("ix_payments_tenant_provider_created", "payments", ["tenant_id", "provider", "created_at"]),
    (
        "ix_ledger_entries_tenant_type_created",
        "ledger_entries",
        ["tenant_id", "entry_type", "created_at"],
    ),
    (
        "ix_subscriptions_tenant_status_period",
        "subscriptions",
        ["tenant_id", "status", "current_period_end"],
    ),
    ("ix_users_tenant_created", "users", ["tenant_id", "created_at"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_code, permission_code) "
            "VALUES (:r, :p) ON CONFLICT DO NOTHING"
        ),
        {"r": NEW_ROLE, "p": PERMISSION},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE role_code = :r AND permission_code = :p"),
        {"r": NEW_ROLE, "p": PERMISSION},
    )
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
