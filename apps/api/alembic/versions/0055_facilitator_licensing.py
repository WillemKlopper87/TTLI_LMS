"""Facilitator licensing: licences and seat grants (2026-09-11-facilitator-licensing-xapi-design.md §3).

Revision ID: 0055
Revises: 0054

Creates the core licensing data model: facilitators (as Organisation kind='licensee')
license courses/learning paths for their own clients with seat pools. Every licensee's
seat pool is the sum of active licences' seats_purchased. Each learner enrolled under
a licence ties usage to billing via licence_seat_grants.

`seats_used` is cached and queried, never stored in a trigger (compliance: the count
must always remain queryable and correct; denormalisation is the cache, not the source
of truth).

UNIQUE (organisation_id, course_id) WHERE status = 'active' prevents two active
licences on the same course for the same licensee. Renewal creates a new licence row;
the old one expires and its existing learners retain access until their entitlement
expiry, no new seats.

`organisations.kind` is shared with the partner portal (0054), which created the
`organisation_kind` enum ('standard', 'partner', 'client'). This migration originally
added its own `kind` varchar ('corporate'/'licensee'); the two are one column, so it
now extends the enum with 'licensee' instead. 'standard' replaces 'corporate' as the
default for ordinary organisations. Downgrade cannot remove an enum value in
PostgreSQL, so 'licensee' stays in the type — harmless, and re-upgrading is idempotent
(ADD VALUE IF NOT EXISTS).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED = ("licences", "licence_seat_grants")
APP_ROLE = "app_user"


def upgrade() -> None:
    # 'licensee' joins the enum 0054 created; the new value is not used within
    # this transaction, which is what PostgreSQL requires of ADD VALUE.
    op.execute("ALTER TYPE organisation_kind ADD VALUE IF NOT EXISTS 'licensee'")
    op.add_column(
        "organisations",
        sa.Column("logo_object_key", sa.Text(), nullable=True),
    )

    # Main licences table
    op.create_table(
        "licences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # XOR: either course_id or learning_path_id is set, never both
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "learning_path_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("seats_purchased", sa.Integer(), nullable=False),
        sa.Column(
            "seats_used",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_per_seat_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("royalty_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Constraint: at most one of course_id or learning_path_id
    op.execute(
        """
        ALTER TABLE licences
        ADD CONSTRAINT ck_licence_course_xor_path
        CHECK (
            (course_id IS NOT NULL AND learning_path_id IS NULL) OR
            (course_id IS NULL AND learning_path_id IS NOT NULL)
        )
        """
    )

    # Constraint: status must be one of the valid values
    op.execute(
        """
        ALTER TABLE licences
        ADD CONSTRAINT ck_licence_status_valid
        CHECK (status IN ('active', 'suspended', 'expired'))
        """
    )

    # Unique on (organisation_id, course_id) when status = 'active'
    # Split into two partial indexes for the two cases (course or path active)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_licences_org_course_active
        ON licences (organisation_id, course_id)
        WHERE status = 'active' AND course_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_licences_org_path_active
        ON licences (organisation_id, learning_path_id)
        WHERE status = 'active' AND learning_path_id IS NOT NULL
        """
    )

    # Seat grant table
    op.create_table(
        "licence_seat_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "licence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("licences.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "entitlement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "learner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_licence_seat_grant_unique",
        "licence_seat_grants",
        ["licence_id", "learner_user_id"],
        unique=True,
    )

    # RLS policies: both tables are tenant-scoped
    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )

    # Grants to app role
    for table in TENANT_SCOPED:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    # Drop RLS policies
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop tables (cascade handles the dependencies)
    op.drop_table("licence_seat_grants")
    op.drop_table("licences")

    # Remove columns from organisations
    op.drop_column("organisations", "logo_object_key")
    # organisations.kind belongs to 0054; the 'licensee' enum value stays (see docstring).
