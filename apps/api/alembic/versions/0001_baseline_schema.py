"""Baseline schema: tenancy, identity, RBAC, audit — with row-level security.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg
from src.core.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables carrying tenant_id. Everything here gets RLS; everything not here is a
# global lookup that must be readable before a tenant is known.
TENANT_SCOPED = ("users", "role_assignments", "audit_events")

APPEND_ONLY = ("audit_events",)

ALL_TABLES = (
    "tenants",
    "tenant_domains",
    "permissions",
    "roles",
    "role_permissions",
    "users",
    "role_assignments",
    "audit_events",
)

# The role the application connects as (DATABASE_URL). It is not the table
# owner and not a superuser, so FORCE ROW LEVEL SECURITY actually binds it —
# unlike the migration connection (DATABASE_URL_SYNC), which is a superuser
# and bypasses RLS unconditionally regardless of FORCE.
APP_ROLE = "app_user"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", pg.CITEXT(), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("settings", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "feature_flags", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ai_monthly_token_budget", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "tenant_domains",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("hostname", pg.CITEXT(), nullable=False, unique=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tls_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "uq_tenant_domains_primary",
        "tenant_domains",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "permissions",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
    )

    op.create_table(
        "roles",
        sa.Column("code", sa.String(48), primary_key=True),
        sa.Column("name", sa.String(96), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_code",
            sa.String(48),
            sa.ForeignKey("roles.code", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_code",
            sa.String(64),
            sa.ForeignKey("permissions.code", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("email_blind_index", sa.LargeBinary(), nullable=False),
        sa.Column("email_domain", pg.CITEXT(), nullable=False),
        sa.Column("full_name_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("phone_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("guest_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("mfa_enforced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email_domain", "users", ["email_domain"])
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])
    # Unique per tenant, not globally — the same person may hold accounts with
    # two different corporate customers.
    op.create_index(
        "uq_users_tenant_email", "users", ["tenant_id", "email_blind_index"], unique=True
    )
    op.create_index(
        "ix_users_guest_expiry",
        "users",
        ["guest_expires_at"],
        postgresql_where=sa.text("is_guest"),
    )

    op.create_table(
        "role_assignments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_code",
            sa.String(48),
            sa.ForeignKey("roles.code", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("organisation_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_role_assignments_tenant_id", "role_assignments", ["tenant_id"])
    op.create_index("ix_role_assignments_user_id", "role_assignments", ["user_id"])
    # NULLS NOT DISTINCT so a second tenant-wide assignment of the same role
    # collides instead of quietly duplicating. Postgres 15+.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_role_assignment
        ON role_assignments (tenant_id, user_id, role_code, organisation_id)
        NULLS NOT DISTINCT
        """
    )

    op.create_table(
        "audit_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(48), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("before", pg.JSONB(), nullable=True),
        sa.Column("after", pg.JSONB(), nullable=True),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_tenant_created", "audit_events", ["tenant_id", "created_at"])

    # --- Append-only enforcement -------------------------------------------
    #
    # A raising trigger rather than a DO INSTEAD NOTHING rule. A rule makes the
    # write a silent no-op, so a buggy code path that tries to amend an audit
    # row appears to succeed. This fails loudly and can be asserted in a test.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refuse_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'append_only_violation: % is append-only', TG_TABLE_NAME
                USING ERRCODE = '42501';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in APPEND_ONLY:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION refuse_mutation();
            """
        )

    # --- Row-level security -------------------------------------------------
    #
    # FORCE as well as ENABLE: the application connects as the table owner in
    # development, and owners bypass RLS unless forced.
    #
    # NULLIF turns the unset GUC (empty string) into NULL, so an unscoped
    # session matches nothing rather than erroring on ''::uuid. Fails closed.
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

    # --- Least-privileged application role ----------------------------------
    #
    # The migration connection (DATABASE_URL_SYNC) is a superuser, needed for
    # DDL. A superuser bypasses RLS unconditionally, FORCE or not, so the
    # running application must never connect as it — it connects as this role
    # instead. Password comes from Settings so it is never a literal here in
    # anything but the local/CI fallback.
    app_password = (get_settings().app_db_password or "app_user_local_dev").replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{app_password}';
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    for table in ALL_TABLES:
        if table in APPEND_ONLY:
            # No UPDATE/DELETE grant, on top of the trigger — belt and braces,
            # and it matches the grant documented in 02_DATA_MODEL.md §1.5.
            op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        else:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS refuse_mutation()")

    op.drop_table("audit_events")
    op.drop_table("role_assignments")
    op.drop_table("users")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_index("uq_tenant_domains_primary", table_name="tenant_domains")
    op.drop_table("tenant_domains")
    op.drop_table("tenants")

    # Dropping the tables above already revokes every grant on them; the role
    # itself would otherwise persist as an empty, unreferenced login.
    op.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
