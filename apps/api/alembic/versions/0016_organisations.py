"""Phase 5 sprint 1: organisations, seats, PO checkout (02 §4.5,
REQ-TEN-02). Closes Phase 3's deferred PO-capture gap and Phase 5's
organisations/seats requirement together — the PRD's own worked example
("organisation admin selects seats → PO number and document captured →
pro-forma issued → finance approves → seats activated → admin invites
learners") is one vertical slice, not two features that happen to touch
each other.

`entitlements.organisation_id` and `role_assignments.organisation_id`
already existed as bare, unconstrained uuid columns from `0001`/`0009` —
02 §4.7 and §4.6 documented them ("organisation-level entitlements exist
before seat assignment"; "a person can be a manager in one organisation
and an ordinary learner in another") years before `organisations` itself
could exist to be pointed at. This migration is mostly that promise
being kept: two `ADD CONSTRAINT` calls, not two new columns.

**Seat assignment reuses `entitlements`, not a new join table.** An org
buying N seats for a course creates one `entitlements` row with
`organisation_id` set and `user_id` NULL — the pool `02 §4.7` describes.
Assigning a seat to a specific employee creates a second entitlements
row, `user_id` set, drawn from that pool; "available seats" is computed
(`quantity` on org-level rows minus count of non-revoked person-level
rows for the same org+course), not a separately maintained counter that
could drift from reality. Revoking a seat sets the existing
`revoked_at` column — already there, unused until now.

`organisations.seat_count` from 02 §4.5's own field list is deliberately
not included: it would be a second, manually-set number describing the
same thing `entitlements.quantity` already computes correctly, and a
field nothing keeps in sync is worse than no field.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("organisations", "organisation_members")


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        # 02 §4.5: "VAT number (encrypted), billing address (encrypted)" —
        # a business identifier and a physical address, encrypted like
        # any other PII-adjacent field in this codebase; no blind index
        # on either, since nothing looks an organisation up by them.
        sa.Column("vat_number_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("billing_address_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("payment_terms", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_organisations_tenant_id", "organisations", ["tenant_id"])

    op.create_table(
        "organisation_members",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "organisation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 02 §4.5's exact wording: "a relationship column (member,
        # manager, admin) — the manager relationship is an ABAC input,
        # so it is a first-class row, not a role string." Not the RBAC
        # `roles`/`role_assignments` system — this is org structure
        # (who is in the org, and their standing in it), a different
        # question from "what platform permissions does this user hold."
        sa.Column("relationship", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_organisation_members_tenant_id", "organisation_members", ["tenant_id"])
    op.create_index(
        "uq_organisation_members_org_user",
        "organisation_members",
        ["organisation_id", "user_id"],
        unique=True,
    )

    op.add_column(
        "orders",
        sa.Column(
            "organisation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    # Keeping two promises 0001 and 0009 made before organisations
    # existed to be pointed at (see this migration's own docstring).
    op.create_foreign_key(
        "fk_entitlements_organisation_id",
        "entitlements",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_role_assignments_organisation_id",
        "role_assignments",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

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
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    # orders' first writable column since 0009 — same UPDATE-only
    # precedent 0012/0014 set for lessons/courses.
    op.execute(f"GRANT UPDATE ON orders TO {APP_ROLE}")

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES "
            "('organisation:manage', 'View and manage any organisation in the tenant')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_code, permission_code) VALUES "
            "('admin', 'organisation:manage'), ('super_admin', 'organisation:manage')"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Dangling references would otherwise survive the dropped tables and break
    # `create_foreign_key` on a subsequent re-upgrade.
    conn.execute(
        sa.text("UPDATE entitlements SET organisation_id = NULL WHERE organisation_id IS NOT NULL")
    )
    conn.execute(
        sa.text(
            "UPDATE role_assignments SET organisation_id = NULL WHERE organisation_id IS NOT NULL"
        )
    )
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = 'organisation:manage'")
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE code = 'organisation:manage'"))

    op.execute(f"REVOKE UPDATE ON orders FROM {APP_ROLE}")
    op.drop_constraint(
        "fk_role_assignments_organisation_id", "role_assignments", type_="foreignkey"
    )
    op.drop_constraint("fk_entitlements_organisation_id", "entitlements", type_="foreignkey")
    op.drop_column("orders", "organisation_id")

    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_table("organisation_members")
    op.drop_table("organisations")
