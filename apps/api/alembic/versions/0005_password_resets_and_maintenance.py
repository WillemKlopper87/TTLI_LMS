"""Sprint 5: password resets; maintenance functions the worker can call.

The two maintenance jobs (extending the monthly events partitions, purging
expired auth rows) need privileges app_user deliberately does not have —
DDL on the partitioned parent, and DELETE across every tenant despite RLS.
Rather than handing the worker a superuser connection, each job is a
SECURITY DEFINER function owned by the migration role; app_user gets
EXECUTE and nothing else. The worker (src/workers/main.py) just calls them.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.create_table(
        "password_resets",
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
        sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_password_resets_tenant_id", "password_resets", ["tenant_id"])
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])

    op.execute("ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_resets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON password_resets
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON password_resets TO {APP_ROLE}")

    # --- Maintenance functions ---------------------------------------------
    #
    # SET search_path pins name resolution — the standard hardening for
    # SECURITY DEFINER, since the function runs with its owner's privileges.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION extend_events_partitions(months_ahead int DEFAULT 12)
        RETURNS int
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            start_month date := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
            m date;
            part_name text;
            created int := 0;
        BEGIN
            FOR i IN 0..months_ahead LOOP
                m := (start_month + make_interval(months => i))::date;
                part_name := 'events_' || to_char(m, 'YYYY_MM');
                IF to_regclass(part_name) IS NULL THEN
                    EXECUTE format(
                        'CREATE TABLE %I PARTITION OF events FOR VALUES FROM (%L) TO (%L)',
                        part_name, m, (m + make_interval(months => 1))::date
                    );
                    created := created + 1;
                END IF;
            END LOOP;
            RETURN created;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION purge_expired_auth_rows(grace_days int DEFAULT 30)
        RETURNS int
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            cutoff timestamptz := now() - make_interval(days => grace_days);
            n int;
            total int := 0;
        BEGIN
            DELETE FROM refresh_tokens WHERE expires_at < cutoff;
            GET DIAGNOSTICS n = ROW_COUNT; total := total + n;
            DELETE FROM magic_links WHERE expires_at < cutoff;
            GET DIAGNOSTICS n = ROW_COUNT; total := total + n;
            DELETE FROM password_resets WHERE expires_at < cutoff;
            GET DIAGNOSTICS n = ROW_COUNT; total := total + n;
            RETURN total;
        END;
        $$;
        """
    )
    for fn in ("extend_events_partitions(int)", "purge_expired_auth_rows(int)"):
        op.execute(f"REVOKE EXECUTE ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_expired_auth_rows(int)")
    op.execute("DROP FUNCTION IF EXISTS extend_events_partitions(int)")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON password_resets")
    op.drop_table("password_resets")
