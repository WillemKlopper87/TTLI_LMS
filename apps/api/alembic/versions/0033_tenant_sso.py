"""Per-tenant OIDC single sign-on (`docs/BACKLOG.md` P4, feature-matrix
gap #46) — the standard corporate procurement gate for the Team and
Corporate tiers.

One row per tenant: a tenant either has an identity provider or it does
not, and a second one would raise "which IdP does this login belong to?"
at the exact moment there is no session to ask. Hence the unique index
on `tenant_id` rather than a plain FK.

**`client_secret_encrypted` is bytes, encrypted like every other secret
in this schema** (04 §4.2's field-encryption rule — the same treatment
`users.email_encrypted` and `organisations` VAT numbers get). A client
secret in clear would be the one credential in this database that lets
someone impersonate the whole tenant to its own IdP.

`allowed_email_domains` is the account-takeover guard and is not
optional in practice: JIT provisioning trusts the IdP's email claim, so
without a domain allowlist a misconfigured or hostile IdP could assert
`ceo@some-other-company.com` and be handed an account. Stored as a
Postgres text[] so the check is a containment query rather than a JSON
scan.

`group_role_map` maps an IdP group claim value to a role code. It is
JSONB rather than a table because it is configuration a tenant edits as
a whole, never joins against — the same reasoning `tenants.settings`
already follows.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.create_table(
        "tenant_idp_configs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Only OIDC today. SAML is the other half of gap #46 and needs a
        # different verification model entirely, so the column exists to
        # make that addition a value rather than a schema change.
        sa.Column("protocol", sa.String(16), nullable=False, server_default="oidc"),
        # What the sign-in button says. "Sign in with Microsoft" is not
        # something this platform should guess on a tenant's behalf.
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("allowed_email_domains", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "group_role_map", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        # Granted to every user this IdP provisions. Nullable: a tenant
        # may want SSO users to arrive with no authority at all until an
        # administrator gives them some.
        sa.Column("default_role_code", sa.String(48), nullable=True),
        # A config can exist while it is still being set up. Nothing
        # half-configured should appear on a login page.
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_tenant_idp_configs_tenant", "tenant_idp_configs", ["tenant_id"], unique=True
    )

    op.execute("ALTER TABLE tenant_idp_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_idp_configs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_idp_configs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    # SELECT, INSERT, UPDATE, DELETE: unlike the append-only financial
    # tables, an IdP config is live configuration a tenant edits and
    # removes. Every verb the service layer issues is granted here —
    # 0020 and 0022 exist because earlier migrations forgot one.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_idp_configs TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_idp_configs")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON tenant_idp_configs FROM {APP_ROLE}")
    op.drop_index("uq_tenant_idp_configs_tenant", table_name="tenant_idp_configs")
    op.drop_table("tenant_idp_configs")
