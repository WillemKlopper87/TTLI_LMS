"""Pre/post survey pairing for privacy-gated skills deltas (P9 phase 2).

`pair_id` is a report grouping key, never a respondent identifier. A partial
unique index permits at most one pre and one post survey in a pair. Existing
surveys remain standalone byte-for-byte.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = postgresql.ENUM("standalone", "pre", "post", name="survey_evaluation_role")
    role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "surveys",
        sa.Column("evaluation_role", role, nullable=False, server_default="standalone"),
    )
    op.add_column("surveys", sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_check_constraint(
        "ck_surveys_evaluation_pair",
        "surveys",
        "(evaluation_role = 'standalone' AND pair_id IS NULL) OR "
        "(evaluation_role IN ('pre', 'post') AND pair_id IS NOT NULL)",
    )
    op.create_index(
        "uq_surveys_pair_pre",
        "surveys",
        ["pair_id"],
        unique=True,
        postgresql_where=sa.text("evaluation_role = 'pre'"),
    )
    op.create_index(
        "uq_surveys_pair_post",
        "surveys",
        ["pair_id"],
        unique=True,
        postgresql_where=sa.text("evaluation_role = 'post'"),
    )


def downgrade() -> None:
    op.drop_index("uq_surveys_pair_post", table_name="surveys")
    op.drop_index("uq_surveys_pair_pre", table_name="surveys")
    op.drop_constraint("ck_surveys_evaluation_pair", "surveys", type_="check")
    op.drop_column("surveys", "pair_id")
    op.drop_column("surveys", "evaluation_role")
    postgresql.ENUM(name="survey_evaluation_role").drop(op.get_bind(), checkfirst=True)
