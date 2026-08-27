"""Tenant-scoped reusable quiz and survey question templates (P9 phase 3).

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.create_table(
        "question_bank_items",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("assessment_kind", sa.String(length=16), nullable=False),
        sa.Column("question_type", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", pg.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("points", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("assessment_kind IN ('quiz', 'survey')", name="ck_question_bank_kind"),
        sa.CheckConstraint("points > 0", name="ck_question_bank_points_positive"),
    )
    op.create_index(
        "ix_question_bank_items_tenant_kind",
        "question_bank_items",
        ["tenant_id", "assessment_kind"],
    )
    op.execute("ALTER TABLE question_bank_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE question_bank_items FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON question_bank_items
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON question_bank_items TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("ALTER TABLE question_bank_items NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON question_bank_items")
    op.execute(f"REVOKE ALL ON question_bank_items FROM {APP_ROLE}")
    op.drop_table("question_bank_items")
