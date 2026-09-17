"""Partner portal models and relationships (§4 of 2026-09-11-partner-portal-design.md).

Revision ID: 0047
Revises: 0046

§4.1 Client organisations under a partner:
  - Add parent_organisation_id (self-referential, nullable FK to organisations)
  - Add organisations.kind enum: 'standard' (default, every ordinary org),
    'partner', 'client'. Originally defaulted new AND existing rows to
    'partner', which silently granted every organisation (including via
    the pre-existing self-service org-creation flow) the ability to create
    client organisations under itself — corrected to default 'standard';
    services/partner.py::activate_partner promotes an org to 'partner'
    only once its partner profile actually clears activation.

§4.2 Assessment licences:
  - assessment_licences table with template_id as unconstrained nullable UUID
  - template_id is deferred cross-feature FK (defined in assessment platform spec)

§4.3 Partner profile and agreements:
  - partner_profiles table with field-level encryption for registration_number
  - Linked to organisations via unique FK
  - Status gates activation on MFA + agreement + (for health professionals) registration

All new tenant-scoped tables have row-level security policies and are granted to app_user.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    # §4.1: Extend organisations table with parent_organisation_id and kind enum
    # First, create the organisation_kind enum type if it doesn't exist
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE organisation_kind AS ENUM ('standard', 'partner', 'client');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )

    # Add parent_organisation_id (self-referential FK)
    op.add_column(
        "organisations",
        sa.Column(
            "parent_organisation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    # Add kind column with default value. 'standard' — not 'partner' — so
    # every pre-existing organisation, and every new one created by the
    # unrelated self-service org-creation flow, stays a plain org unless
    # and until it is explicitly promoted (see activate_partner).
    op.execute(
        "ALTER TABLE organisations ADD COLUMN kind organisation_kind NOT NULL DEFAULT 'standard'"
    )

    # §4.2: Create assessment_licences table
    op.create_table(
        "assessment_licences",
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
        # template_id is deferred cross-feature FK (assessment_templates will be created
        # in assessment platform spec; this is an unconstrained nullable UUID for now)
        sa.Column("template_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("runs_purchased", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requires_ttli_review", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("price_per_run_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("order_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_assessment_licences_tenant_id", "assessment_licences", ["tenant_id"])
    op.create_index("ix_assessment_licences_organisation_id", "assessment_licences", ["organisation_id"])
    op.create_index("ix_assessment_licences_template_id", "assessment_licences", ["template_id"])

    # RLS for assessment_licences
    op.execute("ALTER TABLE assessment_licences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assessment_licences FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON assessment_licences
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON assessment_licences TO {APP_ROLE}")

    # §4.3: Create partner_profiles table
    op.create_table(
        "partner_profiles",
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
            unique=True,
        ),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("logo_object_key", sa.Text(), nullable=True),
        sa.Column("professional_body", sa.Text(), nullable=True),
        sa.Column("registration_number_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("operator_agreement_ref", sa.Text(), nullable=True),
        sa.Column("operator_agreement_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="invited",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_partner_profiles_tenant_id", "partner_profiles", ["tenant_id"])
    op.create_index("ix_partner_profiles_organisation_id", "partner_profiles", ["organisation_id"])

    # RLS for partner_profiles
    op.execute("ALTER TABLE partner_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE partner_profiles FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON partner_profiles
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON partner_profiles TO {APP_ROLE}")


def downgrade() -> None:
    # Drop partner_profiles table and its RLS policy
    op.execute("ALTER TABLE partner_profiles NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON partner_profiles")
    op.execute(f"REVOKE ALL ON partner_profiles FROM {APP_ROLE}")
    op.drop_table("partner_profiles")

    # Drop assessment_licences table and its RLS policy
    op.execute("ALTER TABLE assessment_licences NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON assessment_licences")
    op.execute(f"REVOKE ALL ON assessment_licences FROM {APP_ROLE}")
    op.drop_table("assessment_licences")

    # Drop parent_organisation_id column and kind column
    op.drop_column("organisations", "kind")
    op.drop_column("organisations", "parent_organisation_id")

    # Drop the organisation_kind enum type
    op.execute("DROP TYPE IF EXISTS organisation_kind")
