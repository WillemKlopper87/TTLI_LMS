"""Close the cross-tenant bespoke-course residual services/courses.py::
assign_course_to_tenant documents.

Revision ID: 0047
Revises: 0046

`course_tenant_assignments` carries FORCE ROW LEVEL SECURITY (0011): a
query inside tenant B's request transaction cannot see tenant A's row at
all, so the self-service assignment path had no query it could run to
tell "already exclusively claimed bespoke by another tenant" apart from
"unclaimed" — assign_course_to_tenant's own docstring called this out
explicitly rather than papering over it with a check that silently
always evaluated false.

Same fix as 0005's purge_expired_auth_rows and 0032's
prune_idempotency_keys: a SECURITY DEFINER function, owned by the
migration role (a superuser, which Postgres always exempts from RLS
regardless of FORCE), doing the one cross-tenant read the app role
itself can never perform. It answers a single yes/no question — is this
course already bespoke to a DIFFERENT tenant — never returns which
tenant or any other row data, so it cannot become a new disclosure
channel the way a general cross-tenant SELECT would.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION course_claimed_bespoke_by_other_tenant(
            p_course_id uuid, p_tenant_id uuid
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            claimed boolean;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM course_tenant_assignments
                WHERE course_id = p_course_id
                  AND is_bespoke = true
                  AND tenant_id <> p_tenant_id
            ) INTO claimed;
            RETURN claimed;
        END;
        $$;
        """
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION course_claimed_bespoke_by_other_tenant(uuid, uuid) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"course_claimed_bespoke_by_other_tenant(uuid, uuid) TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS course_claimed_bespoke_by_other_tenant(uuid, uuid)")
